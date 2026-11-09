"""Optional guidance regressions. EVERY real engine has exactly 300 guests."""
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bailey_motion import BaileyEngine,UserModel,default_config
from bailey_motion import geometry as G, plans
from bailey_motion.crowd_managers import options,signal,valid_layout
from bailey_motion.crowd_routes import region_distance
from bailey_motion.crowd_optimize import optimize,objective,audience_fingerprint
from bailey_motion.records import Record,record
from bailey_motion.plan_viewer import draw


def engine(enabled=True,**overrides):
    w=default_config(); w.population=300
    if enabled or overrides: w.crowdManagers=Record(enabled=enabled,**overrides)
    return BaileyEngine(w,UserModel({'pairedRandomness':True}))


def move(e,a,region,x,y,floor=0,zone=None):
    e._index_remove(a)
    a.update(region=region,x=x,y=y,floor=floor,zone=zone,vx=0.,vy=0.)
    e._index_add(a)


class CrowdManagerTests(unittest.TestCase):
    def test_disabled_mode_preserves_rng_agents_and_portals(self):
        baseline=engine(False); explicit=engine(False,count=6,positions=[])
        baseline.run_steps(40); explicit.run_steps(40)
        self.assertIsNone(baseline.crowd); self.assertIsNone(explicit.crowd)
        self.assertEqual(baseline.agents,explicit.agents)
        self.assertEqual(baseline.portals,explicit.portals)
        self.assertEqual((baseline.rng.s,baseline.rng.spare),(explicit.rng.s,explicit.rng.spare))
        self.assertNotIn('crowdManagers',baseline.export())

    def test_initial_audience_and_four_weights_match(self):
        a=engine(False); b=engine()
        self.assertEqual(audience_fingerprint(a),audience_fingerprint(b))
        self.assertEqual((a.rng.s,a.rng.spare),(b.rng.s,b.rng.spare))
        self.assertEqual(len(b.agents),300); self.assertEqual(len(b.crowd.managers),6)
        self.assertTrue(all(set(x.data.weights)=={'T','P','N','S'} for x in b.agents))

    def test_seat_inventory_reachable_and_staff_layout_feasible(self):
        e=engine(); c=e.crowd
        self.assertEqual(len(c.seat_routes),1329)
        self.assertEqual(len(c.assignments),1329)
        self.assertTrue(valid_layout(c.config.positions,c.sites,c.config))
        for item in c.seat_routes:
            self.assertIsNotNone(item.route)
            route=item.route
            self.assertGreater(route.distance,0)
            self.assertEqual(c.graph.portals[route.exitId].floor,0)
            self.assertEqual(c.graph.portals[route.exitId].type,'exit')
            self.assertNotIn('ADA_W',route.portals)
            if item.seatLabel.startswith('B'):
                self.assertTrue(any(c.graph.portals[p].type=='stairs' for p in route.portals))
            if item.seatLabel.startswith('O'):
                self.assertTrue(any(c.graph.portals[p].type=='access' for p in route.portals))

    def test_annulus_chord_and_obstacle_detour(self):
        e=engine(); g=e.g; R=g.regions.corridor.minR
        a,b=G.point(26.,.5,g),G.point(26.,.6,g)
        self.assertAlmostEqual(region_distance(g,'corridor',a,b),G.distance(a,b))
        a,b=G.point(R,.1,g),G.point(R,2.,g)
        self.assertAlmostEqual(region_distance(g,'corridor',a,b),1.9*R)
        self.assertGreater(region_distance(g,'corridor',a,b),G.distance(a,b))

    def test_dijkstra_matches_independent_bellman_relaxation(self):
        e=engine(); graph=e.crowd.graph; blocked={'SIDE_E1','BACK_W','AUD4'}
        expected={n:math.inf for n in graph.nodes}
        for p in graph.portals.values():
            if p.type=='exit' and p.id not in blocked: expected['P:'+p.id]=0.
        for _ in range(len(graph.nodes)):
            changed=False
            for start,edges in graph.edges.items():
                for end,length,gate in edges:
                    if gate not in blocked and expected[end]+length<expected[start]-1e-10:
                        expected[start]=expected[end]+length; changed=True
            if not changed: break
        actual,_,_=graph.field(blocked)
        for node in actual:
            if math.isinf(expected[node]): self.assertTrue(math.isinf(actual[node]))
            else: self.assertAlmostEqual(actual[node],expected[node],places=8)

    def test_closing_all_exits_returns_unreachable_without_json_infinity(self):
        e=engine(); graph=e.crowd.graph
        blocked={p.id for p in graph.portals.values() if p.type=='exit'}
        self.assertIsNone(graph.seat_route(e.seats[0],blocked).route)
        json.dumps(graph.seat_route(e.seats[0],blocked),allow_nan=False)

    def test_obstruction_truth_notification_and_known_route_are_separate(self):
        e=engine(closures=[dict(portalId='M2',at=10.,notifyAfter=15.)]); c=e.crowd
        p=e.portal_map['M2']; m=c.managers[0]
        self.assertGreater(G.distance(m,p),e.policy.settings.discoveryRadius)
        e.t=9.; c.before_tick(); self.assertTrue(p.enabled)
        e.t=10.; c.before_tick(); self.assertFalse(p.enabled); self.assertNotIn('M2',m.knownBlocked)
        a=e.agents[0]; move(e,a,'foyer',0.,40.)
        action=e.policy.local.action(a,e.context(a),p)
        self.assertEqual(c.graph.action_route(a,action).exitId,'M2')
        self.assertIsNone(c.graph.action_route(a,action,{'M2'}))
        e.t=25.; c.before_tick(); self.assertTrue(all('M2' in m.knownBlocked for m in c.managers))

    def test_signal_floor_range_wall_and_distance(self):
        e=engine(); c=e.crowd.config
        a=Record(x=0.,y=37.,floor=0); m=Record(x=1.,y=37.,floor=0)
        q=signal(a,m,e.g,e.portals,c)
        self.assertAlmostEqual(q,math.exp(-1/c.decayLength))
        m.x=2.; self.assertLess(signal(a,m,e.g,e.portals,c),q)
        m.floor=1; self.assertEqual(signal(a,m,e.g,e.portals,c),0.)
        m.floor=0; m.x=100.; self.assertEqual(signal(a,m,e.g,e.portals,c),0.)
        m.x=2.; e.g.visibilityWalls=[Record(floor=0,start=Record(x=1,y=36),end=Record(x=1,y=38))]
        self.assertEqual(signal(a,m,e.g,e.portals,c),0.)

    def test_assigned_manager_wins_over_stronger_conflicting_instruction(self):
        e=engine(); c=e.crowd; a=e.agents[0]
        move(e,a,'foyer',0.,37.)
        assigned=next(m for m in c.managers if m.managerId==a.data.guidance.responsibleManager)
        other=next(m for m in c.managers if m is not assigned)
        for m in c.managers: m.floor=1
        assigned.update(floor=0,x=8.,y=37.,knownBlocked=['M2'])
        other.update(floor=0,x=1.,y=37.,knownBlocked=[])
        e.portal_map['M2'].enabled=False
        actions=[e.policy.local.action(a,e.context(a),e.portal_map[p]) for p in ('M2','M4')]
        self.assertGreater(signal(a,other,e.g,e.portals,c.config),signal(a,assigned,e.g,e.portals,c.config))
        self.assertEqual(c.graph.recommend(a,actions,other.knownBlocked).actionId,'M2')
        self.assertEqual(c.graph.recommend(a,actions,assigned.knownBlocked).actionId,'M4')
        original=a.data.guidance.responsibleManager
        instruction=c.receive(a,actions,'foyer-test')
        self.assertEqual(instruction.managerId,original)
        self.assertEqual(instruction.actionId,'M4')
        self.assertAlmostEqual(instruction.signal,math.exp(-8/c.config.decayLength))
        self.assertEqual(a.data.guidance.responsibleManager,original)
        self.assertEqual(c.assignments[a.seat.label],original)

    def test_unreachable_assigned_manager_allows_fallback_then_regains_priority(self):
        e=engine(); c=e.crowd; a=e.agents[0]
        move(e,a,'foyer',0.,37.)
        original=a.data.guidance.responsibleManager
        assigned=next(m for m in c.managers if m.managerId==original)
        other=next(m for m in c.managers if m is not assigned)
        for m in c.managers: m.floor=1
        other.update(floor=0,x=1.,y=37.)
        actions=[e.policy.local.action(a,e.context(a),e.portal_map['M2'])]
        for reason in ('range','floor','wall'):
            with self.subTest(reason=reason):
                assigned.update(floor=0,x=8.,y=37.)
                e.g.visibilityWalls=[]
                if reason=='range': assigned.x=50.
                elif reason=='floor': assigned.floor=1
                else: e.g.visibilityWalls=[Record(floor=0,start=Record(x=4.,y=36.),end=Record(x=4.,y=38.))]
                self.assertEqual(c.receive(a,actions,'foyer-test').managerId,other.managerId)
                self.assertEqual(a.data.guidance.responsibleManager,original)
                assigned.update(floor=0,x=8.,y=37.); e.g.visibilityWalls=[]
                self.assertEqual(c.receive(a,actions,'foyer-test').managerId,original)

    def test_fallback_uses_strongest_signal_and_stable_ties(self):
        e=engine(); c=e.crowd; a=e.agents[0]
        move(e,a,'foyer',0.,37.)
        assigned=next(m for m in c.managers if m.managerId==a.data.guidance.responsibleManager)
        alternatives=[m for m in c.managers if m is not assigned][:2]
        for m in c.managers: m.floor=1
        alternatives[0].update(floor=0,x=2.,y=37.)
        alternatives[1].update(floor=0,x=1.,y=37.)
        actions=[e.policy.local.action(a,e.context(a),e.portal_map['M2'])]
        self.assertEqual(c.receive(a,actions,'foyer-test').managerId,alternatives[1].managerId)
        alternatives[0].x=-1.
        self.assertEqual(c.receive(a,actions,'foyer-test').managerId,min(m.managerId for m in alternatives))

    def test_physical_staff_are_not_behavioral_peers(self):
        e=engine(); a=e.agents[0]; m=e.crowd.managers[0]
        move(e,a,m.standingRegion,m.x+.5,m.y,m.floor)
        self.assertIn(m,e.neighbors(a,2.))
        self.assertFalse(e._clear(a,m.x,m.y))
        e.policy.local.before_tick(e.context())
        self.assertTrue(all(b.id>=0 for b in e.policy.local.observed(a,e.context(a))))

    def test_guidance_arithmetic_argmax_and_finite_export(self):
        e=engine(); e.run_steps(50)
        count=0
        for a in e.agents:
            decision=a.data.get('lastDecision')
            if not decision: continue
            count+=1
            scores=decision.alternatives
            self.assertEqual(decision.chosen,max(scores,key=lambda s:s.utility).id)
            self.assertEqual(decision.choiceWithoutGuidanceBonus,max(scores,key=lambda s:s.utility-s.guidanceBonus).id)
            self.assertEqual(decision.guidanceChangedChoice,decision.chosen!=decision.choiceWithoutGuidanceBonus)
            for s in scores:
                self.assertAlmostEqual(s.utility,s.behavioral+s.distance+s.panic+s.residual+s.guidanceBonus)
        self.assertGreater(count,0)
        self.assertGreater(e.crowd.summary()['recommendedDecisions'],0)
        json.dumps(e.export(),allow_nan=False)

    def test_memory_retains_route_but_expires_and_invalidates_on_news(self):
        e=engine(); a=e.agents[0]; c=e.crowd
        move(e,a,'foyer',0.,37.)
        action=e.policy.local.action(a,e.context(a),e.portal_map['M2'])
        a.data.guidance.memory=Record(actionId='M2',portals=['M2'],exitId='M2',distance=4.2,
                                     stage='foyer-test',signal=1.,receivedAt=0.,expiresAt=60.,managerId='CM1')
        for m in c.managers: m.floor=1
        e.t=30.
        self.assertIsNotNone(c.receive(a,[action],'foyer-test'))
        self.assertAlmostEqual(c.bonus(a,action),c.config.strength*math.exp(-.5))
        e.t=61.; self.assertIsNone(c.receive(a,[action],'foyer-test'))
        e.t=30.
        a.data.guidance.memory=Record(actionId='M2',portals=['M2'],stage='foyer-test',signal=1.,
                                     receivedAt=0.,expiresAt=60.,managerId='CM1')
        a.data.knownBlocked=['M2']; self.assertIsNone(c.receive(a,[action],'foyer-test'))

    def test_route_memory_advances_without_new_global_search(self):
        e=engine(); a=e.agents[0]; c=e.crowd
        for m in c.managers: m.floor=1
        move(e,a,'rim',0.,30.7)
        a.data.guidance.memory=Record(actionId='ROW_LEFT',portals=['ACCESS2','AUD4','F1','M2'],
                                     stage='old-row',signal=.8,receivedAt=0.,expiresAt=60.,managerId='CM1')
        options=[e.policy.local.action(a,e.context(a),e.portal_map[p]) for p in ('AUD0','AUD4')]
        with patch.object(c.graph,'recommend',side_effect=AssertionError('No new global search allowed')):
            memory=c.receive(a,options,'new-rim')
        self.assertEqual(memory.actionId,'AUD4'); self.assertEqual(memory.receivedAt,0.)

    def test_gui_form_opt_in_and_opt_out_preserve_other_parameters(self):
        from bailey_motion.app import BaileyApp
        class Value:
            def __init__(self,value): self.value=value
            def get(self): return self.value
            def set(self,value): self.value=value
        app=BaileyApp.__new__(BaileyApp)
        app.world=default_config()
        app.population=Value('300'); app.seed=Value('2026'); app.dt=Value('.1')
        app.collisions=Value(True); app.regions=Value(True); app.capacity=Value(True)
        app.crowd_enabled=Value(True)
        app.students_enabled=Value(False)
        app.led_enabled=Value(False); app.led_strength=Value('12')
        on=app.settings_from_form()
        self.assertTrue(on.crowdManagers.enabled)
        self.assertEqual(on.geometry,app.world.geometry)
        app.world=on; app.crowd_enabled.set(False)
        self.assertFalse(app.settings_from_form().crowdManagers.enabled)

    def test_cli_mode_flags_and_manager_settings_override(self):
        from bailey_motion.cli import main
        def invoke(arguments):
            out=io.StringIO()
            with redirect_stdout(out): status=main(['--n','300','--ticks','0']+arguments)
            self.assertEqual(status,2)  # deliberate zero-tick, incomplete run
            return json.loads(out.getvalue())
        self.assertNotIn('crowdManagers',invoke([]))
        self.assertEqual(invoke(['--crowd-managers'])['crowdManagers']['count'],6)
        off=invoke(['--manager-settings',str(ROOT/'crowd_manager_settings.json'),'--no-crowd-managers'])
        self.assertNotIn('crowdManagers',off)

    def test_counter_shocks_do_not_advance_mechanics_rng(self):
        e=engine(False); a=e.agents[0]; old=(e.rng.s,e.rng.spare)
        first=e.policy.shock(a,e.context(a),'M0','residual')
        e.policy.shock(a,e.context(a),'M1','residual')
        a.data.noiseCache.clear()
        self.assertEqual(e.policy.shock(a,e.context(a),'M0','residual'),first)
        self.assertEqual(old,(e.rng.s,e.rng.spare))

    def test_objective_never_drops_incomplete_runs(self):
        def run(remaining,time):
            return dict(weight=1.,summary=dict(remaining=remaining,population=300,clearanceTime=time))
        self.assertLess(objective([run(0,100.)],120.),objective([run(1,None)],120.))
        self.assertEqual(objective([run(0,10.),run(0,20.)],120.),(0.,0.,15.))

    def test_optimizer_exact_six_cache_and_heldout_protocol(self):
        world=default_config(); world.population=300
        calls=[]
        closure=dict(portalId='M2',at=10,notifyAfter=15)
        def fake_run(w,c,settings,positions,seed,scenario,enabled=True):
            self.assertEqual(scenario['closures'],[closure])
            calls.append((tuple(positions),seed,enabled))
            time=50.+sum(map(len,positions))/100+(0. if enabled else 10.)
            return dict(seed=seed,scenario=scenario['name'],weight=scenario['weight'],audienceFingerprint=str(seed),
                        summary=dict(remaining=0,population=300,clearanceTime=time))
        with patch('bailey_motion.crowd_optimize.run_case',fake_run):
            result=optimize(world,manager_config={'closures':[closure]},population_size=3,generations=1)
        self.assertEqual(len(set(result['bestManagerSettings'].positions)),6)
        self.assertEqual(result['validationSeeds'],[7])
        self.assertEqual(sum(seed==7 for _,seed,_ in calls),2)
        self.assertEqual(len({layout for layout,seed,_ in calls if seed==2026}),len(result['training']))
        self.assertLessEqual(result['history'][-1]['objective'],result['history'][0]['objective'])
        json.dumps(result,allow_nan=False)

    def test_validation_and_gui_render_without_tk_session(self):
        for values in ({'count':5},{'strength':-1},{'positions':['x']*6}):
            with self.assertRaises(ValueError): options(Record(crowdManagers=values))
        e=engine()
        class Canvas:
            def winfo_width(self): return 540
            def winfo_height(self): return 610
            def __getattr__(self,name): return lambda *args,**kwargs:None
        canvas=Canvas(); canvas._bailey_geometry_key=None
        self.assertGreater(draw(canvas,e,0,0).scale,0.)


if __name__=='__main__': unittest.main()
