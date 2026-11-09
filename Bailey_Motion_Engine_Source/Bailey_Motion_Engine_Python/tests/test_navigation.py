"""Regression cases for edge-waypoint stalls and opposing-flow deadlocks."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bailey_motion import default_config, BaileyEngine, UserModel
from bailey_motion import geometry as G, navigation
from bailey_motion.records import Record


def engine(n=1):
    world = default_config()
    world.population = n
    return BaileyEngine(world, UserModel())


def place(e, a, **changes):
    e._index_remove(a)
    a.update(floor=0, planId="main", vx=0, vy=0)
    a.update(changes)
    a.params.reaction = 0
    a.data.started = True
    a.data.nextDecision = 1e9
    e._index_add(a)


class NavigationTests(unittest.TestCase):
    def test_side_door_approach_aligns_before_crossing_outer_wall(self):
        e = engine()
        a, p = e.agents[0], e.portal_map["SIDE_E1"]
        position = G.point(27.298, p.angle - .039, e.g)
        place(e, a, region="corridor", zone=None, **position)
        a.data.portal = p.id
        goal = e.policy.goal(a, e.context(a))
        self.assertLess(G.radius(goal, e.g), G.radius(a, e.g))
        for _ in range(150):
            e.step()
            if a.exited:
                break
        self.assertTrue(a.exited)
        self.assertEqual(a.exitThreshold.portalId, p.id)

    def test_radial_correction_cannot_create_subarrival_dead_zone(self):
        e = engine()
        a = e.agents[0]
        place(e, a, region="rim", zone="loge", **G.point(22.26, 1.89, e.g))
        a.data.portal = "AUD5"
        goal = e.policy.goal(a, e.context(a))
        # Previously this was a .0225 m radial waypoint, inside the .025 m
        # arrival tolerance, which returned zero velocity forever.
        self.assertGreater(G.distance(a, goal), .025)
        e.run_steps(150)
        self.assertNotEqual(a.region, "rim")

    def test_narrow_access_centers_body_before_barrier_edge(self):
        e = engine()
        a, p = e.agents[0], e.portal_map["ACCESS2"]
        r = e.g.zones.orchestra.maxR - .01
        place(e, a, region="aisle", zone="orchestra", aisleAngle=p.angle,
              **G.point(r, p.angle + .85 / r, e.g))
        a.data.portal = p.id
        self.assertTrue(G.inside_region(a, a.x, a.y, e.g))
        goal = e.policy.goal(a, e.context(a))
        self.assertLess(G.radius(goal, e.g), r)
        for _ in range(200):
            e.step()
            if a.transfers:
                break
        self.assertTrue(any(t.sourcePortal == p.id for t in a.transfers))

    def test_head_on_pair_passes_without_overlap_or_exit_reassignment(self):
        e = engine(2)
        targets = ["AUD8", "AUD0"]
        for a, theta, target in zip(e.agents, (1.4, 1.44), targets):
            place(e, a, region="rim", zone="loge", **G.point(23.15, theta, e.g))
            a.data.portal = target
        weights = [dict(a.data.weights) for a in e.agents]
        for _ in range(120):
            previous = [(a.x, a.y) for a in e.agents]
            e.step()
            self.assertGreaterEqual(G.distance(*e.agents), sum(a.radius for a in e.agents) * math.sqrt(1.005) - 1e-8)
            for a, (x, y) in zip(e.agents, previous):
                self.assertLessEqual(math.hypot(a.x - x, a.y - y), .7 + 1e-9)
                self.assertTrue(G.inside_region(a, a.x, a.y, e.g))
        self.assertGreater(G.polar(e.agents[0], e.g), G.polar(e.agents[1], e.g))
        self.assertEqual([a.data.portal for a in e.agents], targets)
        self.assertEqual([dict(a.data.weights) for a in e.agents], weights)
        self.assertTrue(any(a.data.navigation.avoidanceSteps > 0 for a in e.agents))

    def test_local_avoidance_can_be_disabled_and_consumes_no_random_draws(self):
        e = engine()
        a = e.agents[0]
        place(e, a, region="rim", zone="loge", **G.point(23.15, 1.4, e.g))
        a.data.portal = "AUD8"
        goal = e.policy.goal(a, e.context(a))
        proposed = Record(vx=0, vy=0)
        state = (e.rng.s, e.rng.spare)
        e.policy.settings.localAvoidance = False
        self.assertIs(navigation.steer(a, e.context(a), goal, proposed, [], e.policy.settings), proposed)
        e.policy.settings.localAvoidance = True
        navigation.steer(a, e.context(a), goal, proposed, [], e.policy.settings)
        self.assertEqual((e.rng.s, e.rng.spare), state)

    def test_invalid_local_steering_settings_are_rejected(self):
        for settings in ({"localAvoidance": "yes"}, {"avoidanceLookahead": 0},
                         {"passingClearance": -1}, {"progressTimeout": math.nan}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                UserModel(settings)

    def test_steering_does_not_admit_a_disabled_exterior_threshold(self):
        e = engine()
        a, p = e.agents[0], e.portal_map["M2"]
        p.enabled = False
        place(e, a, region="foyer", zone=None, x=0, y=41.1)
        a.data.portal = p.id
        goal = e.policy.goal(a, e.context(a))
        for _ in range(30):
            e.t += e.config.dt
            velocity = navigation.steer(a, e.context(a), goal, Record(vx=0, vy=1), [], e.policy.settings)
            e._move(a, velocity)
            self.assertFalse(a.exited)
            self.assertLessEqual(a.y, p.y + 1e-9)

    def test_small_population_no_longer_remains_in_the_edge_clusters(self):
        e = engine(30)
        e.config.limits.maxSeconds = 120
        e.run()
        self.assertEqual(e.done, 30)
        self.assertEqual(len(e.threshold_events), 30)
        self.assertTrue(all(a.exitThreshold.floor == 0 for a in e.agents))


if __name__ == "__main__":
    unittest.main()
