"""Constant LED utility guidance; all actual engines use 300 audience members."""
import io
import json
import math
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bailey_motion import BaileyEngine,UserModel,default_config
from bailey_motion import geometry as G
from bailey_motion.led_guidance import options,region_path
from bailey_motion.records import Record,record
from bailey_motion.plan_viewer import draw


def engine(enabled=True,students=False,managers=False,**settings):
    w=default_config();w.population=300
    if enabled is not None:w.ledStrips=Record(enabled=enabled,**settings)
    if students:w.studentMode=True
    if managers:w.crowdManagers=Record(enabled=True)
    return BaileyEngine(w,UserModel({'pairedRandomness':True}))


def foyer(e,a,x=0.,y=34.):
    e._index_remove(a);a.update(x=x,y=y,floor=0,region='foyer',zone=None,vx=0.,vy=0.)
    a.params.reaction=0.;e.policy.local.clear_target(a);e._index_add(a)


def normalized_agents(e):
    agents=record(e.agents)
    for a in agents:
        a.data.pop('led',None)
        decision=a.data.get('lastDecision')
        if decision:
            for key in ('led','ledStrength','choiceWithoutLEDBonus','ledChangedChoice'):decision.pop(key,None)
            for alternative in decision.alternatives:alternative.pop('ledBonus',None)
    return agents


class LEDTests(unittest.TestCase):
    def test_disabled_mode_preserves_baseline(self):
        a,b=engine(None),engine(False)
        a.run_steps(40);b.run_steps(40)
        self.assertIsNone(a.led);self.assertIsNone(b.led)
        self.assertEqual(a.agents,b.agents);self.assertEqual(a.portals,b.portals)
        self.assertEqual((a.rng.s,a.rng.spare),(b.rng.s,b.rng.spare))

    def test_constant_bonus_does_not_decay_with_distance_or_time(self):
        e=engine();a=e.agents[0];foyer(e,a)
        near=e.policy.local.action(a,e.context(a),e.portal_map['M2'])
        options=e.policy.local.available_actions(a,e.context(a))
        self.assertEqual(e.led.instruction(a,options).actionId,'M2')
        self.assertEqual(e.led.bonus(a,near),12.)
        foyer(e,a,y=40.);e.t=100.
        self.assertEqual(e.led.bonus(a,near),12.)
        e.led.config.strength=27.
        self.assertEqual(e.led.bonus(a,near),27.)
        other=e.policy.local.action(a,e.context(a),e.portal_map['M4'])
        self.assertEqual(e.led.bonus(a,other),0.)

    def test_zero_strength_has_no_behavior_or_information_effect(self):
        a,b=engine(None),engine(strength=0.)
        a.run_steps(50);b.run_steps(50)
        self.assertEqual(a.agents,normalized_agents(b));self.assertEqual(a.portals,b.portals)
        self.assertEqual((a.rng.s,a.rng.spare),(b.rng.s,b.rng.spare))
        self.assertEqual(b.led.summary()['recommendedDecisions'],0)

    def test_only_indicated_target_is_revealed(self):
        e=engine();a=e.agents[0];foyer(e,a,x=-9.,y=37.)
        a.data.arrivalMemory.knownTargets=[];a.data.knownTargets={}
        e.policy.settings.visionRange=.001
        choices=e.policy.local.perceived_actions(a,e.context(a))
        self.assertEqual([x.id for x in choices],['M0'])
        self.assertEqual(choices[0].perception,'led')
        self.assertEqual(set(a.data.knownTargets),{'M0'})
        self.assertIsNone(e.students);self.assertIsNone(e.crowd)

    def test_led_is_a_soft_bonus_not_student_route_override(self):
        e=engine();e.policy.settings.behavioralOnly=True
        a=e.agents[0];foyer(e,a,y=37.)
        choices=e.policy.local.perceived_actions(a,e.context(a))
        self.assertEqual(a.data.led.instruction.actionId,'M2')
        a.data.weights=Record(T=1.,P=100.,N=0.,S=0.)
        def features(a,api,action,*args):return Record(T=0.,P=float(action.id=='M4'),N=0.,C=0.)
        with patch.object(e.policy.local,'features',side_effect=features):
            self.assertEqual(e.policy.local.choose(a,e.context(a),choices).id,'M4')

    def test_adaptive_controller_reroutes_without_granting_global_guest_knowledge(self):
        e=engine();a=e.agents[0];foyer(e,a)
        actions=e.policy.local.available_actions(a,e.context(a))
        self.assertEqual(e.led.instruction(a,actions).actionId,'M2')
        e.portal_map['M2'].enabled=False;e.led.before_tick()
        route=e.led.instruction(a,actions)
        self.assertNotEqual(route.actionId,'M2');self.assertNotIn('M2',route.portals)
        self.assertNotIn('M2',a.data.knownBlocked)
        self.assertIn('M2',e.led.blocked)

    def test_static_lighting_stays_stale_until_guest_rejects_known_blocked_route(self):
        e=engine(adaptive=False);a=e.agents[0];foyer(e,a)
        e.portal_map['M2'].enabled=False;e.led.before_tick()
        actions=e.policy.local.available_actions(a,e.context(a))
        self.assertEqual(e.led.instruction(a,actions).actionId,'M2')
        a.data.knownBlocked=['M2']
        actions=e.policy.local.available_actions(a,e.context(a))
        self.assertIsNone(e.led.instruction(a,actions))

    def test_students_suppress_leds_entirely(self):
        e=engine(students=True,managers=True)
        self.assertIsNotNone(e.students);self.assertIsNone(e.led);self.assertIsNone(e.crowd)
        self.assertTrue(all('led' not in a.data and 'guidance' not in a.data for a in e.agents))

    def test_manager_and_led_bonuses_add_and_diagnostics_are_exact(self):
        e=engine(managers=True);a=e.agents[0];foyer(e,a,y=37.)
        assigned=a.data.guidance.responsibleManager
        for m in e.crowd.managers:m.update(floor=1)
        manager=next(m for m in e.crowd.managers if m.managerId==assigned)
        manager.update(floor=0,x=1.,y=37.)
        self.assertIs(e.led.graph,e.crowd.graph)
        actions=e.policy.local.perceived_actions(a,e.context(a))
        e.policy.local.choose(a,e.context(a),actions)
        decision=a.data.lastDecision
        self.assertEqual(decision.guidance.managerId,assigned)
        for score in decision.alternatives:
            self.assertAlmostEqual(score.utility,score.behavioral+score.distance+score.panic+score.residual+score.guidanceBonus+score.ledBonus)
        self.assertEqual(decision.chosen,max(decision.alternatives,key=lambda x:x.utility).id)
        self.assertEqual(decision.choiceWithoutLEDBonus,max(decision.alternatives,key=lambda x:x.utility-x.ledBonus).id)
        json.dumps(e.export(),allow_nan=False)

    def test_no_routes_means_no_instruction_or_misleading_strips(self):
        e=engine();a=e.agents[0]
        for p in e.portals:
            if p.type=='exit':p.enabled=False
        e.led.before_tick()
        self.assertIsNone(e.led.instruction(a,e.policy.local.available_actions(a,e.context(a))))
        self.assertEqual(e.led.display_paths(),[])

    def test_curved_display_and_rendering_do_not_change_simulation(self):
        e=engine();R=e.g.regions.corridor.minR
        path=region_path(e.g,'corridor',G.point(26.,.1,e.g),G.point(26.,3.,e.g))
        self.assertGreater(len(path),2)
        self.assertTrue(all(G.radius(p,e.g)>=R-1e-7 for p in path))
        before=e.export();rng=(e.rng.s,e.rng.spare)
        class Canvas:
            def winfo_width(self):return 540
            def winfo_height(self):return 610
            def __getattr__(self,name):return lambda *args,**kwargs:None
        canvas=Canvas();canvas._bailey_geometry_key=None
        draw(canvas,e,0);draw(canvas,e,1)
        self.assertTrue(e.led.display_paths())
        self.assertEqual(before,e.export());self.assertEqual(rng,(e.rng.s,e.rng.spare))

    def test_validation_and_cli_controls(self):
        from bailey_motion.cli import main
        for values in ({'strength':-1},{'strength':math.nan},{'adaptive':'yes'},{'enabled':1}):
            with self.subTest(values=values),self.assertRaises(ValueError):options(Record(ledStrips=values))
        out=io.StringIO()
        with redirect_stdout(out):status=main(['--n','300','--ticks','0','--led-strips','--led-strength','7.5'])
        self.assertEqual(status,2);self.assertEqual(json.loads(out.getvalue())['ledStrips']['strength'],7.5)
        out=io.StringIO()
        with redirect_stdout(out):main(['--n','300','--ticks','0','--led-settings',str(ROOT/'led_settings.json'),'--no-led-strips'])
        self.assertNotIn('ledStrips',json.loads(out.getvalue()))


if __name__=='__main__':unittest.main()
