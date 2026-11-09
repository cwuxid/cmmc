"""Opt-in sample-average placement search; standard library only.

The simulator is the objective evaluator. Coverage initializes the search but
does not rank evacuation layouts. Six DISTINCT candidate locations form an
unordered chromosome; canonical sorting caches permutations as one layout.
Training seeds select placements; held-out seeds only report final performance.
"""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from .config import default_config, validate_config
from .crowd_managers import candidates, initial_layout, options, valid_layout
from .engine import BaileyEngine
from .geometry import build_seats
from .records import Record, record, finite
from .user_model import UserModel


def audience_fingerprint(engine):
    """Hash every initial audience attribute that must be matched across runs."""
    audience=[dict(id=a.id,seat=a.seat.label,params=a.params,weights=a.data.weights,
                   panic=a.data.panicSensitivity,betaDistance=a.data.betaDistance) for a in engine.agents]
    return hashlib.sha256(json.dumps(audience,sort_keys=True,allow_nan=False).encode()).hexdigest()


def run_case(world,manager_config,policy_settings,positions,seed,scenario,enabled=True):
    w=record(world); w.seed=seed
    w.crowdManagers=record(manager_config)
    w.crowdManagers.update(enabled=enabled,positions=list(positions),closures=record(scenario['closures']))
    settings=record(policy_settings or {}); settings.pairedRandomness=True
    e=BaileyEngine(w,UserModel(settings))
    fingerprint=audience_fingerprint(e)
    e.run()
    summary=e.summary()
    if e.crowd: summary['guidance']=e.crowd.summary()
    times=sorted(a.exitAt for a in e.agents if a.exited)
    rank=math.ceil(.95*len(e.agents))
    summary['time95']=times[rank-1] if len(times)>=rank else None
    return dict(seed=seed,scenario=scenario['name'],weight=scenario['weight'],
                audienceFingerprint=fingerprint,summary=summary)


def objective(runs,horizon):
    """Lexicographic: failure probability, remaining fraction, capped time.

    An incomplete run is NEVER discarded or treated as cleared at horizon.
    Its restricted time is H, its true clearanceTime stays null. Failure and
    remaining fraction precede speed, so a fast partial evacuation cannot beat
    a fully completed one. With all runs complete, the last term is mean T100.
    """
    total=sum(r['weight'] for r in runs)
    if not runs or total<=0: raise ValueError('Objective needs positive-weight runs.')
    failed=remaining=restricted=0.
    for r in runs:
        s=r['summary']; weight=r['weight']/total
        failed+=weight*int(s['remaining']>0)
        remaining+=weight*s['remaining']/s['population']
        restricted+=weight*(s['clearanceTime'] if s['clearanceTime'] is not None else horizon)
    return (failed,remaining,restricted)


def normalize_scenarios(scenarios):
    scenarios=scenarios if scenarios is not None else [dict(name='open',closures=[],weight=1.)]
    if not isinstance(scenarios,list) or not scenarios: raise ValueError('Need at least one scenario.')
    result=[]
    for scenario in scenarios:
        if not isinstance(scenario,dict): raise ValueError('Each scenario must be an object.')
        name,weight=scenario.get('name'),scenario.get('weight',1.)
        if not isinstance(name,str) or not name or not finite(weight) or weight<=0:
            raise ValueError('Scenarios need unique names and positive finite weights.')
        if any(s['name']==name for s in result): raise ValueError('Duplicate scenario name.')
        closures=scenario.get('closures',[])
        if not isinstance(closures,list): raise ValueError('Scenario closures must be a list.')
        result.append(dict(name=name,weight=weight,closures=record(closures)))
    return result


def optimize(world,manager_config=None,policy_settings=None,scenarios=None,training_seeds=(2026,),
             validation_seeds=(7,),population_size=6,generations=3,search_seed=314159,progress=None):
    """Return a best-found discrete placement, not a global-optimality claim.

    Scenario weights are normalized in objective(); seeds have equal weight.
    Staff coefficients stay fixed. Search RNG is isolated from audience RNG.
    Cache survives all generations; validation never changes the chosen layout.
    """
    validate_config(world)
    if world.get('studentMode',False):
        raise ValueError('Student mode has no crowd managers; disable it before optimizing staff positions.')
    for seeds in (training_seeds,validation_seeds):
        if not seeds or len(set(seeds))!=len(seeds) or any(type(s)is not int or not 0<=s<=0xffffffff for s in seeds):
            raise ValueError('Use nonempty lists of distinct unsigned 32-bit audience seeds.')
    if set(training_seeds)&set(validation_seeds): raise ValueError('Training and held-out seeds must be disjoint.')
    if type(population_size)is not int or population_size<2 or type(generations)is not int or generations<0:
        raise ValueError('Search population >=2 and generations >=0 are required.')
    if type(search_seed)is not int: raise ValueError('search_seed must be an integer.')
    c=options(Record(crowdManagers=manager_config or {})); c.enabled=True
    # A manager-settings file can itself describe a blocked-exit experiment.
    # Preserve it unless an explicit scenario list overrides that schedule.
    if scenarios is None:
        scenarios=[dict(name='configured-closures' if c.closures else 'open',weight=1.,closures=record(c.closures))]
    scenarios=normalize_scenarios(scenarios)
    seats=build_seats(world.geometry); sites=candidates(world.geometry,seats,c.managerRadius)
    initial=c.positions or initial_layout(sites,seats,world.geometry,c)
    if not valid_layout(initial,sites,c): raise ValueError('Invalid starting layout.')
    rng=random.Random(search_seed); ids=sorted(sites); cache={}; history=[]
    def announce(message):
        if progress: progress(message)
    def sample(parent=None,other=None):
        for _ in range(2000):
            if parent is None:
                proposed=rng.sample(ids,6)
            else:
                pool=list(dict.fromkeys(list(parent)+list(other or parent)))
                proposed=rng.sample(pool,6)
                # At least one mutation keeps crossover from exhausting a small
                # initial union; random replacement can alter floor allocation.
                for _ in range(1+(rng.random()<.25)):
                    proposed[rng.randrange(6)]=rng.choice(ids)
            proposed=tuple(sorted(proposed))
            if valid_layout(proposed,sites,c): return proposed
        raise RuntimeError('Could not sample a compatible six-manager layout.')
    def evaluate(layout):
        if layout not in cache:
            runs=[]
            for seed in training_seeds:
                for scenario in scenarios:
                    announce(f'Layout {len(cache)+1}: seed {seed}, {scenario["name"]}')
                    runs.append(run_case(world,c,policy_settings,layout,seed,scenario))
            cache[layout]=dict(positions=list(layout),objective=list(objective(runs,world.limits.maxSeconds)),runs=runs)
        return cache[layout]
    population=[tuple(sorted(initial))]
    while len(population)<population_size:
        p=sample()
        if p not in population: population.append(p)
    best=None
    for generation in range(generations+1):
        for layout in population: evaluate(layout)
        population.sort(key=lambda p:(tuple(cache[p]['objective']),p))
        best=population[0]
        history.append(dict(generation=generation,bestPositions=list(best),objective=cache[best]['objective'],evaluatedLayouts=len(cache)))
        announce(f'Generation {generation}: objective {cache[best]["objective"]}')
        if generation==generations: break
        next_population=[best]
        while len(next_population)<population_size:
            def parent():
                contest=rng.sample(population,min(3,len(population)))
                return min(contest,key=lambda p:(tuple(cache[p]['objective']),p))
            child=sample(parent(),parent())
            if child not in next_population: next_population.append(child)
        population=next_population
    validation=[]
    for seed in validation_seeds:
        for scenario in scenarios:
            announce(f'Held-out seed {seed}, {scenario["name"]}: baseline and selected layout')
            baseline=run_case(world,c,policy_settings,best,seed,scenario,False)
            guided=run_case(world,c,policy_settings,best,seed,scenario,True)
            if baseline['audienceFingerprint']!=guided['audienceFingerprint']:
                raise RuntimeError('Paired audience initialization changed.')
            b,g=baseline['summary']['clearanceTime'],guided['summary']['clearanceTime']
            validation.append(dict(baseline=baseline,guided=guided,
                                   clearanceDifferenceSeconds=g-b if b is not None and g is not None else None))
    selected=record(c); selected.positions=list(best)
    return dict(method='discrete genetic simulation search; best found, no global guarantee',
                population=world.population,world=record(world),policySettings=record(policy_settings or {}),
                pairedRandomness=True,trainingSeeds=list(training_seeds),validationSeeds=list(validation_seeds),
                searchSeed=search_seed,searchPopulation=population_size,generations=generations,scenarios=scenarios,
                objectiveOrder=['failureProbability','meanRemainingFraction','meanRestrictedClearanceSeconds'],
                bestManagerSettings=selected,training=sorted(cache.values(),key=lambda x:(x['objective'],x['positions'])),
                history=history,validation=validation)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Optional six-manager placement optimizer (can take substantial time).')
    parser.add_argument('--n',type=int,default=300)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--manager-settings',type=Path)
    parser.add_argument('--settings',type=Path,help='Bundled behavior settings overrides.')
    parser.add_argument('--scenarios',type=Path,help='JSON list of {name,weight,closures}.')
    parser.add_argument('--training-seeds',type=int,nargs='+',default=[2026])
    parser.add_argument('--validation-seeds',type=int,nargs='+',default=[7])
    parser.add_argument('--search-population',type=int,default=6)
    parser.add_argument('--generations',type=int,default=3)
    parser.add_argument('--search-seed',type=int,default=314159)
    parser.add_argument('--max-seconds',type=float,default=180.)
    parser.add_argument('--output',required=True,help='New report inside the Python project.')
    parser.add_argument('--layout-output',help='New manager settings JSON reusable in GUI/CLI.')
    args=parser.parse_args(argv)
    try:
        from .cli import output_path
        report_path=output_path(args.output)
        layout_path=output_path(args.layout_output) if args.layout_output else None
        if layout_path==report_path: raise ValueError('Report and layout paths must differ.')
        def read(path): return json.loads(path.read_text(encoding='utf-8')) if path else None
        world=record(read(args.config)) if args.config else default_config()
        world.population=args.n; world.limits.maxSeconds=args.max_seconds
        result=optimize(world,read(args.manager_settings),read(args.settings),read(args.scenarios),
                        args.training_seeds,args.validation_seeds,args.search_population,args.generations,
                        args.search_seed,lambda s:print(s,flush=True))
        with report_path.open('x',encoding='utf-8') as f: json.dump(result,f,indent=2,allow_nan=False)
        if layout_path:
            with layout_path.open('x',encoding='utf-8') as f: json.dump(result['bestManagerSettings'],f,indent=2,allow_nan=False)
        print(json.dumps(dict(report=str(report_path),best=result['training'][0]['objective'],
                              positions=result['bestManagerSettings']['positions']),indent=2))
        return 0
    except (ValueError,OSError,TypeError,KeyError,RuntimeError,AttributeError) as error:
        parser.exit(1,f'Error: {error}\n')


if __name__=='__main__': raise SystemExit(main())
