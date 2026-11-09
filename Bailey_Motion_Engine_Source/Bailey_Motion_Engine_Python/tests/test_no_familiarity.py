"""Four-factor utility regressions; every engine here has exactly 300 units."""
import csv
import io
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bailey_motion import BaileyEngine, UserModel, default_config
from bailey_motion.behavior import behavioral_utility
from bailey_motion.config import legacy_config
from bailey_motion.loader import compile_policy, default_policy_source
from bailey_motion.records import Record, record
from archived_five_weight_policy import ArchivedUserModel


def engine(legacy=False, settings=None):
    world = legacy_config() if legacy else default_config()
    world.population = 300
    return BaileyEngine(world, UserModel(settings))


class NoFamiliarityTests(unittest.TestCase):
    def test_only_four_weights_settings_features_and_csv_columns(self):
        e = engine(settings={'familiarBuildingExit':'M2'})
        self.assertNotIn('familiarBuildingExit', e.policy.settings)
        before = [record(a.data.weights) for a in e.agents]
        self.assertTrue(all(list(w) == ['T','P','N','S'] for w in before))
        e.run_steps(50)
        self.assertEqual(before, [a.data.weights for a in e.agents])
        decisions = [a.data.lastDecision for a in e.agents if 'lastDecision' in a.data]
        self.assertTrue(decisions)
        for decision in decisions:
            for option in decision.alternatives:
                self.assertNotIn('H', option.features)
        rows = list(csv.reader(io.StringIO(e.agents_csv(True))))
        self.assertEqual(rows[0][-4:], ['wT','wP','wN','wS'])
        self.assertNotIn('wH', rows[0])
        self.assertEqual(len(rows), 301)
        json.dumps(e.export(), allow_nan=False)

    def test_old_habit_values_cannot_affect_dot_product(self):
        weights = Record(T=1., P=0., N=0., S=0., H=1e12)
        close = Record(T=.03, P=0., N=0., C=0., H=0.)
        far = Record(T=.18, P=0., N=0., C=0., H=1.)
        self.assertAlmostEqual(behavioral_utility(weights, close), -.03)
        self.assertAlmostEqual(behavioral_utility(weights, far), -.18)
        self.assertGreater(behavioral_utility(weights, close), behavioral_utility(weights, far))

    def test_arrival_knowledge_does_not_reward_an_action(self):
        e = engine(); a = e.agents[0]
        e._index_remove(a)
        a.update(x=0., y=38., region='foyer', zone=None, floor=0, planId='main')
        e._index_add(a)
        action = e.policy.local.action(a, e.context(a), e.portal_map['M2'])
        before = e.policy.local.features(a, e.context(a), action)
        a.data.arrivalMemory.knownTargets = ['M0']
        after = e.policy.local.features(a, e.context(a), action)
        self.assertEqual(before, after)
        self.assertNotIn('H', after)
        self.assertNotIn('familiarTargets', a.data.arrivalMemory)

    def test_legacy_runtime_mode_has_no_familiarity_reward(self):
        for archived_geometry in (False, True):
            with self.subTest(archived_geometry=archived_geometry):
                e = engine(archived_geometry, {'behaviorMode':'legacy'})
                self.assertTrue(all(set(a.data.weights) == {'T','P','N','S'} for a in e.agents))
                a = e.agents[0]
                a.data.weights = Record(T=1., P=0., N=0., S=0., H=1e12)
                a.data.betaCrowd = 0.
                e.policy.peer_share = lambda *args: 0.
                e.policy.norm_violation = lambda *args: 0.
                e.policy.shock = lambda *args: 0.
                options = [Record(id='near', distance=1., estimatedTime=1., habit=0.),
                           Record(id='far', distance=1., estimatedTime=10., habit=1.)]
                self.assertEqual(e.policy.choose(a, e.context(a), options, 'portal').id, 'near')

    def test_four_dimensional_covariance_and_unit_mean_centering(self):
        p = UserModel({'weightSigma':1.2, 'weightRho':-.3})
        draws = []
        weights = p.sample_weights(Record(normal=lambda: draws.append(0.) or 0.))
        self.assertEqual(len(draws), 4)
        self.assertEqual(list(weights), ['T','P','N','S'])
        for value in weights.values(): self.assertAlmostEqual(math.log(value), -.72)
        for i in range(4):
            for j in range(4):
                covariance = sum(p._cholesky[i][k] * p._cholesky[j][k] for k in range(4))
                self.assertAlmostEqual(covariance, 1.44 if i == j else -.432)
                if i == j: self.assertAlmostEqual(math.exp(-.72 + covariance / 2), 1.)
        for rho in (-1/3, 1., float('nan')):
            with self.subTest(rho=rho), self.assertRaises(ValueError):
                UserModel({'weightRho':rho}).sample_weights(Record(normal=lambda:0.))

    def test_editable_bundled_policy_uses_four_weights(self):
        world = default_config(); world.population = 300
        e = BaileyEngine(world, compile_policy(default_policy_source()))
        self.assertTrue(all('H' not in a.data.weights for a in e.agents))

    def test_archived_300_person_fixture_remains_test_only(self):
        # Historical source parity is evaluated with its frozen five-weight test
        # policy, not by reintroducing that policy into production mode switches.
        fixture = json.loads(Path(__file__).with_name('javascript_reference.json').read_text())
        case = next(c for c in fixture['cases'] if c['population'] == 300)
        world = legacy_config(); world.population = 300; world.seed = case['seed']
        e = BaileyEngine(world, ArchivedUserModel())
        def compare(actual, expected):
            if isinstance(expected, dict):
                self.assertEqual(set(actual), set(expected))
                for k in expected: compare(actual[k], expected[k])
            elif isinstance(expected, list):
                self.assertEqual(len(actual), len(expected))
                for a, b in zip(actual, expected): compare(a, b)
            elif type(expected) in (int,float) and type(actual) in (int,float):
                self.assertAlmostEqual(actual, expected, delta=1e-8 + 1e-11 * abs(expected))
            else: self.assertEqual(actual, expected)
        for checkpoint in case['checkpoints']:
            e.run_steps(checkpoint['tick'] - e.tick)
            compare(dict(t=e.t, tick=e.tick, done=e.done, metrics=e.metrics,
                         agents=e.agents, portals=e.portals, history=e.history,
                         rng=dict(s=e.rng.s, spare=e.rng.spare)), checkpoint)


if __name__ == '__main__': unittest.main()
