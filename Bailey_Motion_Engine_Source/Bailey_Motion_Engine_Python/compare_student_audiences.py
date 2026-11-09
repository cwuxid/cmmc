"""Reproducible paired students-versus-behavioral-audience experiment.

This analysis runner does not change defaults or engine mechanics. Both arms
have no staff and all evacuation portals open. 'Randoms' means the existing
heterogeneous utility policy, not uniformly random direction choices.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from bailey_motion import BaileyEngine,UserModel,default_config
from bailey_motion.config import validate_config
from bailey_motion.crowd_optimize import audience_fingerprint
from bailey_motion.records import record


def save(path,data):
    with path.open('x',encoding='utf-8') as output:
        json.dump(data,output,indent=2,allow_nan=False)


def aggregate(runs,populations,seeds,horizon):
    groups=[]
    for n in populations:
        for mode in ('randoms','students'):
            rows=[r for r in runs if r['population']==n and r['mode']==mode]
            complete=all(r['remaining']==0 for r in rows)
            def mean(key):
                values=[r[key] for r in rows]
                return statistics.mean(values) if all(v is not None for v in values) else None
            groups.append(dict(population=n,mode=mode,runs=len(rows),completedRuns=sum(r['remaining']==0 for r in rows),
                               meanClearanceTime=mean('clearanceTime'),
                               sdClearanceTime=statistics.stdev(r['clearanceTime'] for r in rows) if complete and len(rows)>1 else None,
                               meanTime95=mean('time95'),meanAllExitTime=mean('meanAllExitTime'),
                               meanRestrictedExitTime=mean('restrictedMeanExitTime'),
                               meanRemaining=statistics.mean(r['remaining'] for r in rows)))
    pairs=[]
    for n in populations:
        for seed in seeds:
            baseline=next(r for r in runs if r['population']==n and r['seed']==seed and r['mode']=='randoms')
            students=next(r for r in runs if r['population']==n and r['seed']==seed and r['mode']=='students')
            assert baseline['audienceFingerprint']==students['audienceFingerprint']
            b,s=baseline['clearanceTime'],students['clearanceTime']
            pairs.append(dict(population=n,seed=seed,audienceFingerprint=baseline['audienceFingerprint'],
                              randomsClearance=b,studentsClearance=s,
                              clearanceDifference=s-b if b is not None and s is not None else None,
                              percentReduction=100*(b-s)/b if b is not None and s is not None else None,
                              randomsRemaining=baseline['remaining'],studentsRemaining=students['remaining'],
                              restrictedMeanDifference=students['restrictedMeanExitTime']-baseline['restrictedMeanExitTime']))
    differences=[]
    for n in populations:
        rows=[p for p in pairs if p['population']==n]
        values=[p['clearanceDifference'] for p in rows]
        complete=all(v is not None for v in values)
        differences.append(dict(population=n,completePairs=sum(v is not None for v in values),
                                meanPairedClearanceDifference=statistics.mean(values) if complete else None,
                                sdPairedClearanceDifference=statistics.stdev(values) if complete and len(values)>1 else None,
                                meanPairedRestrictedDifference=statistics.mean(p['restrictedMeanDifference'] for p in rows)))
    return dict(horizon=horizon,groups=groups,pairs=pairs,pairedSummary=differences)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--populations',type=int,nargs='+',default=[300,600])
    parser.add_argument('--seeds',type=int,nargs='+',default=[2026,7,17])
    parser.add_argument('--max-seconds',type=float,default=180.)
    parser.add_argument('--dt',type=float,help='Integration timestep; defaults to the current world setting.')
    parser.add_argument('--random-stream',choices=('paired','original'),default='paired',
                        help='Counter-keyed shocks for controlled comparisons, or the ordinary GUI shock stream.')
    parser.add_argument('--output-dir',required=True,help='New directory inside this Python project.')
    args=parser.parse_args(argv)
    if len(set(args.populations))!=len(args.populations) or len(set(args.seeds))!=len(args.seeds):
        parser.error('Population sizes and seeds must be distinct.')
    output=(ROOT/args.output_dir).resolve()
    if output==ROOT or not output.is_relative_to(ROOT) or output.exists():
        parser.error('Choose a new output directory inside this project.')
    base=default_config()
    if args.dt is not None: base.dt=args.dt
    base.limits.maxSeconds=args.max_seconds
    base.pop('crowdManagers',None)
    base.pop('studentMode',None)
    for n in args.populations:
        for seed in args.seeds:
            check=record(base);check.population=n;check.seed=seed;validate_config(check)
    ticks=args.max_seconds/base.dt
    if abs(ticks-round(ticks))>1e-8: parser.error('Horizon must be a multiple of dt.')
    output.mkdir(parents=True)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'bailey_motion').glob('*.py')}
    paired=args.random_stream=='paired'
    metadata=dict(populations=args.populations,seeds=args.seeds,horizon=args.max_seconds,
                  modes=['randoms','students'],pairedAudiences=True,pairedRandomness=paired,
                  randomStream=args.random_stream,managers=False,allExitsOpen=True,
                  world=base,sourceSha256=hashes,
                  interpretation='Randoms use the ordinary heterogeneous utility policy, not random direction selection.')
    save(output/'experiment.json',metadata)
    runs=[]
    for n in args.populations:
        for seed in args.seeds:
            paired_fingerprint=None
            for mode in ('randoms','students'):
                w=record(base);w.population=n;w.seed=seed;w.studentMode=mode=='students'
                engine=BaileyEngine(w,UserModel({'pairedRandomness':paired}))
                assert engine.crowd is None and len(engine.agents)==n
                fingerprint=audience_fingerprint(engine)
                if paired_fingerprint is None:
                    paired_fingerprint=fingerprint
                    save(output/f'cohort-{n}-{seed}.json',dict(audienceFingerprint=fingerprint,
                         agents=[dict(id=a.id,seat=a.seat,params=a.params,weights=a.data.weights,
                                      panic=a.data.panicSensitivity,betaDistance=a.data.betaDistance) for a in engine.agents]))
                else: assert fingerprint==paired_fingerprint
                started=time.perf_counter()
                print(f'BEGIN n={n} seed={seed} mode={mode}',flush=True)
                for _ in range(round(ticks)):
                    if engine.finished:break
                    engine.step()
                    if engine.tick%300==0:
                        print(f'  t={engine.t:.1f}s exited={engine.done}/{n}',flush=True)
                times=sorted(a.exitAt for a in engine.agents if a.exited)
                assert all(a.exitThreshold.floor==0 for a in engine.agents if a.exited)
                done=engine.done==n
                result=dict(population=n,seed=seed,mode=mode,audienceFingerprint=fingerprint,
                            wallSeconds=time.perf_counter()-started,simulatedSeconds=engine.t,
                            status='complete' if done else 'time_limit',exited=engine.done,remaining=n-engine.done,
                            clearanceTime=max(times) if done else None,
                            time95=times[math.ceil(.95*n)-1] if len(times)>=math.ceil(.95*n) else None,
                            meanAllExitTime=statistics.mean(times) if done else None,
                            meanExitTimeAmongExited=statistics.mean(times) if times else None,
                            restrictedMeanExitTime=(sum(min(t,args.max_seconds) for t in times)+(n-engine.done)*args.max_seconds)/n,
                            sectionCounts=dict(Counter(a.seat.section for a in engine.agents)),
                            exitCounts=dict(Counter(a.exitId for a in engine.agents if a.exited)),
                            remainingRegions=dict(Counter(a.region for a in engine.agents if not a.exited)),
                            metrics=engine.metrics,policySettings=engine.policy.settings,
                            studentSummary=engine.students.summary() if engine.students else None)
                runs.append(result)
                save(output/f'run-{n}-{seed}-{mode}.json',result)
                with (output/f'agents-{n}-{seed}-{mode}.csv').open('x',encoding='utf-8',newline='') as f:
                    f.write(engine.agents_csv(True))
                print(json.dumps({k:result[k] for k in ('population','seed','mode','clearanceTime','time95','remaining','wallSeconds')}),flush=True)
    save(output/'summary.json',aggregate(runs,args.populations,args.seeds,args.max_seconds))
    print(f'REPORT {output / "summary.json"}',flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
