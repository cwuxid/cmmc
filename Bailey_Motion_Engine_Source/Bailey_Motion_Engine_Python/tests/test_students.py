"""Student-mode regressions; every actual engine contains 300 guests."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bailey_motion import BaileyEngine,UserModel,default_config
from bailey_motion.config import validate_config,legacy_config
from bailey_motion.crowd_optimize import audience_fingerprint,optimize
from bailey_motion.records import Record
from bailey_motion import perception


def engine(students=True,managers=False,closures=None):
    world=default_config(); world.population=300
    if students is not None: world.studentMode=students
    if managers or closures: world.crowdManagers=Record(enabled=managers,closures=closures or [])
    return BaileyEngine(world,UserModel({'pairedRandomness':True}))


def foyer(e,a,x=0.,y=34.):
    e._index_remove(a)
    a.update(x=x,y=y,floor=0,region='foyer',zone=None,vx=0.,vy=0.)
    a.params.reaction=0.; e.policy.local.clear_target(a)
    e._index_add(a)


class StudentTests(unittest.TestCase):
    def test_disabled_mode_preserves_baseline(self):
        a=engine(None); b=engine(False)
        a.run_steps(40); b.run_steps(40)
        self.assertIsNone(a.students); self.assertIsNone(b.students)
        self.assertEqual(a.agents,b.agents); self.assertEqual(a.portals,b.portals)
        self.assertEqual((a.rng.s,a.rng.spare),(b.rng.s,b.rng.spare))
        self.assertNotIn('studentRouting',a.export())

    def test_student_initialization_matches_audience_and_random_stream(self):
        baseline=engine(False); students=engine()
        self.assertEqual(audience_fingerprint(baseline),audience_fingerprint(students))
        self.assertEqual((baseline.rng.s,baseline.rng.spare),(students.rng.s,students.rng.spare))
        self.assertEqual(len(students.students.seat_routes),1329)
        self.assertTrue(all('student' in a.data and 'guidance' not in a.data for a in students.agents))

    def test_all_300_choose_their_seat_shortest_route_without_utility(self):
        e=engine(); local=e.policy.local
        with patch.object(e.policy,'shock',side_effect=AssertionError('Student route choice must not draw utility shocks')), \
             patch.object(local,'features',side_effect=AssertionError('Student route choice must not score behavioral features')):
            for a in e.agents:
                actions=local.perceived_actions(a,e.context(a))
                chosen=local.choose(a,e.context(a),actions)
                self.assertEqual(chosen.id,a.data.student.initialRoute.actionId)
                self.assertEqual(a.data.lastDecision.chosenExit,a.data.student.initialRoute.exitId)
                scores=[s for s in a.data.lastDecision.alternatives if s.reachable]
                self.assertEqual(chosen.id,min(scores,key=lambda s:(s.routeDistance,s.exitId,s.id)).id)
                self.assertEqual(a.data.lastDecision.selectionMode,'student-shortest-distance')
        self.assertEqual(e.students.summary()['decisions'],300)

    def test_layout_knowledge_bypasses_visibility_for_target_choice(self):
        e=engine(); a=e.agents[0]; foyer(e,a)
        e.policy.settings.visionRange=.01
        e.policy.settings.fieldOfViewDegrees=1.
        target=e.policy.local.action(a,e.context(a),e.portal_map['M2']).target
        self.assertFalse(perception.visible(a,target,e.context(a),e.policy.settings))
        options=e.policy.local.perceived_actions(a,e.context(a))
        self.assertEqual({x.id for x in options},{'M0','M1','M2','M3','M4'})
        self.assertTrue(all(x.perception=='known-layout' for x in options))
        a.data.weights.update(T=0.,P=1e20,N=1e20,S=1e20)
        self.assertEqual(e.policy.local.choose(a,e.context(a),options,current_id='M4').id,'M2')

    def test_students_do_not_magically_know_closures_and_reroute_on_discovery(self):
        e=engine(); a=e.agents[0]; foyer(e,a)
        e.portal_map['M2'].enabled=False
        e.policy.local.decide(a,e.context(a))
        self.assertEqual(a.data.targetId,'M2'); self.assertNotIn('M2',a.data.knownBlocked)
        foyer(e,a,y=40.)
        e.policy.local.decide(a,e.context(a))
        self.assertIn('M2',a.data.knownBlocked)
        self.assertEqual(a.data.targetId,'M1')
        self.assertNotIn('M2',a.data.lastDecision.route.portals)

    def test_unreachable_route_waits_without_resuming_stale_action(self):
        e=engine(); a=e.agents[0]; foyer(e,a)
        e.policy.local.decide(a,e.context(a))
        self.assertIsNotNone(a.data.localAction)
        a.data.knownBlocked=[p.id for p in e.portals if p.type=='exit']
        a.data.nextDecision=0.
        command=e.policy.local.decide(a,e.context(a))
        self.assertEqual(command,dict(vx=0.,vy=0.))
        self.assertIsNone(a.data.localAction); self.assertIsNone(a.data.portal)
        e.t=.1
        self.assertEqual(e.policy.local.decide(a,e.context(a)),dict(vx=0.,vy=0.))
        self.assertGreater(a.data.student.unreachableDecisions,0)
        json.dumps(e.export(),allow_nan=False)

    def test_manager_toggle_has_no_effect_in_student_mode(self):
        off=engine(); on=engine(managers=True)
        self.assertIsNone(on.crowd); self.assertIsNone(off.crowd)
        off.run_steps(50); on.run_steps(50)
        self.assertEqual(off.agents,on.agents); self.assertEqual(off.portals,on.portals)
        self.assertEqual((off.rng.s,off.rng.spare),(on.rng.s,on.rng.spare))
        self.assertNotIn('crowdManagers',on.export())
        self.assertTrue(all('guidance' not in a.data for a in on.agents))

    def test_physical_closure_schedule_remains_but_staff_news_is_absent(self):
        closures=[dict(portalId='M2',at=0.,notifyAfter=0.)]
        e=engine(managers=True,closures=closures)
        self.assertFalse(e.portal_map['M2'].enabled)
        self.assertEqual(e.crowd.managers,[]); self.assertFalse(e.crowd.config.enabled)
        self.assertTrue(all(not a.data.knownBlocked for a in e.agents))
        self.assertIsNone(e.crowd.graph)
        self.assertIsNotNone(e.students.graph)

    def test_cli_and_world_override(self):
        from bailey_motion.cli import main
        def invoke(args):
            out=io.StringIO()
            with redirect_stdout(out): status=main(['--n','300','--ticks','0']+args)
            self.assertEqual(status,2)
            return json.loads(out.getvalue())
        summary=invoke(['--students','--crowd-managers'])
        self.assertTrue(summary['studentMode']['enabled'])
        self.assertNotIn('crowdManagers',summary)
        world=default_config(); world.population=300; world.studentMode=True
        with patch('bailey_motion.cli.default_config',return_value=world):
            self.assertNotIn('studentMode',invoke(['--no-students']))

    def test_invalid_mode_and_incompatible_optimizer_are_rejected(self):
        for value in ('yes',1,None):
            world=default_config(); world.studentMode=value
            with self.subTest(value=value),self.assertRaises(ValueError): validate_config(world)
        world=legacy_config(); world.population=300; world.studentMode=True
        with self.assertRaises(ValueError): validate_config(world)
        world=default_config(); world.population=300; world.studentMode=True
        with self.assertRaisesRegex(ValueError,'no crowd managers'): optimize(world)


if __name__=='__main__': unittest.main()
