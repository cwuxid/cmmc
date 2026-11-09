"""Numerical manuscript examples, singular cases, and live-policy integration."""
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bailey_motion import BaileyEngine, UserModel, default_config
from bailey_motion import geometry as G, plans, social_force as SF
from bailey_motion.records import Record


def person(identity=0, **changes):
    a = Record(id=identity, x=0., y=0., vx=0., vy=0., floor=0,
               params=Record(speed=1.3), data=Record())
    a.update(changes)
    return a


def engine(n=1, settings=None):
    config = default_config()
    config.population = n
    return BaileyEngine(config, UserModel(settings))


class SocialForceTests(unittest.TestCase):
    def assert_vector(self, actual, x, y):
        self.assertAlmostEqual(actual.x, x, places=12)
        self.assertAlmostEqual(actual.y, y, places=12)

    def test_desired_relaxes_toward_unit_egress_direction(self):
        a = person(vx=.1, vy=-.2)
        self.assert_vector(SF.desired_acceleration(a, Record(x=3., y=4.), .5), 1.36, 2.48)

    def test_exact_waypoint_brakes_and_does_not_delete_other_forces(self):
        a = person(vx=.4, vy=-.2)
        settings = UserModel().settings
        settings.relaxationTime = .5
        contact = Record(distance=.15, normal=Record(x=1., y=0.))
        f = SF.components(a, Record(x=0., y=0.), [contact], [], settings)
        self.assert_vector(f.desired, -.8, .4)
        self.assert_vector(f.total, -.8 + settings.obstacleStrength / math.e, .4)

    def test_obstacle_terms_sum_with_individual_comfort_distance(self):
        contacts = [Record(distance=.2, normal=Record(x=1., y=0.)),
                    Record(distance=.4, normal=Record(x=0., y=-1.))]
        self.assert_vector(SF.obstacle_acceleration(contacts, 2., .2), 2 / math.e, -2 / math.e ** 2)
        a, settings = person(), UserModel().settings
        self.assertEqual(SF.comfort_distance(a, settings), settings.comfortDistance)
        a.params.comfortDistance = .3
        self.assertEqual(SF.comfort_distance(a, settings), .3)
        self.assertGreater(SF.obstacle_acceleration(contacts[:1], 2., .3).x,
                           SF.obstacle_acceleration(contacts[:1], 2., .1).x)

    def test_stationary_pair_is_exact_exponential_repulsion(self):
        a, b = person(), person(1, x=2.)
        self.assert_vector(SF.interaction_acceleration(a, [b], .25, 1., 1.), -math.exp(-2), 0.)
        self.assert_vector(SF.interaction_acceleration(b, [a], .25, 1., 1.), math.exp(-2), 0.)

    def test_oblique_relative_velocity_uses_signed_angle_and_normal(self):
        # x_hat=(1,0), lambda*v_ij=(0,1), D=(1,1), theta=-pi/4.
        # Different n/n' make the longitudinal and lateral factors distinguishable.
        a, b = person(vy=1.), person(1, x=1.)
        length = math.sqrt(2)
        attenuation = math.exp(-1 / length)
        longitudinal = math.exp(-(.5 * math.pi / 4 * length) ** 2)
        lateral = math.exp(-(1.5 * math.pi / 4 * length) ** 2)
        force = SF.interaction_acceleration(a, [b], 1., 1.5, .5)
        self.assert_vector(force, -attenuation * (longitudinal + lateral) / length,
                           -attenuation * (longitudinal - lateral) / length)
        mirrored = SF.interaction_acceleration(person(vy=-1.), [b], 1., 1.5, .5)
        self.assert_vector(mirrored, force.x, -force.y)

    def test_approaching_pair_strength_depends_on_relative_velocity(self):
        a, b = person(vx=1.), person(1, x=2., vx=-1.)
        # D has length 1 + .25*(1-(-1)) = 1.5, theta=0.
        self.assert_vector(SF.interaction_acceleration(a, [b], .25, 1., 1.), -math.exp(-2 / 1.5), 0.)

    def test_interactions_sum_and_ignore_self_exited_and_other_floor(self):
        a, b, c = person(), person(1, x=1.), person(2, y=2.)
        ignored = [a, person(3, x=.1, floor=1), person(4, x=.1, exited=True)]
        self.assert_vector(SF.interaction_acceleration(a, [b, c] + ignored, .25, 1., 1.),
                           -math.exp(-1), -math.exp(-2))

    def test_singular_interaction_limits_are_finite(self):
        a = person(vx=-1.)
        # lambda=1 and x_hat=(1,0) give D=0; the noncoincident limit is zero.
        self.assert_vector(SF.interaction_acceleration(a, [person(1, x=1.)], 1., 1., 1.), 0., 0.)
        self.assert_vector(SF.interaction_acceleration(a, [person(1)], 1., 1., 1.), 0., 0.)

    def test_sum_and_explicit_euler_match_hand_example(self):
        settings = UserModel().settings
        settings.relaxationTime, settings.obstacleStrength, settings.comfortDistance = .5, 2., .2
        a, b = person(vx=.1), person(1, x=1., vx=.1)
        contact = Record(distance=.2, normal=Record(x=0., y=1.))
        force = SF.components(a, Record(x=1., y=0.), [contact], [b], settings)
        self.assert_vector(force.total, 2.4 - math.exp(-1), 2 / math.e)
        velocity = SF.integrate(a, force.total, .1)
        self.assertAlmostEqual(velocity.vx, .1 + .1 * (2.4 - math.exp(-1)))
        self.assertAlmostEqual(velocity.vy, .2 / math.e)

    def test_no_hidden_norms_or_interaction_strength_multiplier(self):
        e = engine(2)
        a, b = e.agents
        a.update(x=0., y=0., vx=0., vy=0., floor=0)
        b.update(x=1., y=0., vx=0., vy=0., floor=0)
        e.policy.settings.interactionStrength = 0
        for norms in (0., 1.):
            a.params.norms = norms
            self.assert_vector(e.policy.interaction_acceleration(a, e.context(a), [b]), -math.exp(-1), 0.)
        e.policy.settings.socialForceMode = "legacy"
        self.assert_vector(e.policy.interaction_acceleration(a, e.context(a), [b]), 0., 0.)

    def test_obstacle_samples_include_barrier_and_use_centre_distance(self):
        e = engine()
        a, g = e.agents[0], e.g
        a.update(floor=0, region="aisle", zone="orchestra", aisleAngle=g.aisleAngles[2] * math.pi,
                 **G.point(10., g.aisleAngles[2] * math.pi, g))
        contacts = {c.id: c for c in plans.obstacle_contacts(a, e.context(a))}
        self.assertAlmostEqual(contacts['aisle:right'].distance, g.aisleHalfWidth)
        # Between access openings the physical barrier repels toward the orchestra.
        a.update(region="row", **G.point(g.orchestraBarrier.radius - .4, 1.5, g))
        barrier = next(c for c in plans.obstacle_contacts(a, e.context(a)) if c.id == 'orchestra:barrier')
        self.assertAlmostEqual(barrier.distance, .4 - g.orchestraBarrier.width / 2)
        self.assertLess(barrier.normal.y, 0)

    def test_open_aperture_has_no_wall_even_if_not_selected(self):
        e = engine()
        a = e.agents[0]
        a.update(floor=0, region="foyer", zone=None, x=0., y=40.9)
        a.data.portal = "M0"  # Physically open M2 is still an opening.
        contacts = plans.obstacle_contacts(a, e.context(a))
        self.assertNotIn('foyer:south', [c.id for c in contacts])
        e.portal_map['M2'].enabled = False
        contacts = plans.obstacle_contacts(a, e.context(a))
        south = next(c for c in contacts if c.id == 'foyer:south')
        self.assertAlmostEqual(south.distance, .3)
        self.assert_vector(south.normal, 0., -1.)

    def test_live_diagnostics_export_raw_capped_and_requested_velocity(self):
        e = engine(settings={"localAvoidance": False, "maxSpeedFactor": 100.})
        a = e.agents[0]
        a.vx, a.vy = .1, -.05
        waypoint = Record(x=a.x + 10., y=a.y)
        rng_before = (e.rng.s, e.rng.spare)
        requested = e.policy.compute_velocity(a, e.context(a), waypoint)
        f = a.data.socialForce
        self.assertAlmostEqual(f.rawVelocity.vx, a.vx + e.config.dt * f.total.x)
        self.assertAlmostEqual(f.rawVelocity.vy, a.vy + e.config.dt * f.total.y)
        self.assertEqual(requested, f.rawVelocity)
        self.assertEqual(requested, f.cappedVelocity)
        self.assertEqual(requested, f.requestedVelocity)
        self.assertEqual((e.rng.s, e.rng.spare), rng_before)
        snapshot = e.export()
        json.dumps(snapshot, allow_nan=False)
        snapshot['agents'][0]['data']['socialForce']['total']['x'] += 1
        self.assertNotEqual(snapshot['agents'][0]['data']['socialForce']['total']['x'], f.total.x)

    def test_individual_comfort_distribution_and_settings_validation(self):
        world = default_config()
        world.population = 3
        world.distributions.comfortDistance = Record(type="normal", mean=.3, sd=0.)
        e = BaileyEngine(world, UserModel())
        self.assertTrue(all(a.params.comfortDistance == .3 for a in e.agents))
        self.assertTrue(all(SF.comfort_distance(a, e.policy.settings) == .3 for a in e.agents))
        world.distributions.comfortDistance.mean = 0.
        with self.assertRaises(ValueError):
            BaileyEngine(world, UserModel())
        for overrides in ({"socialForceMode": "other"}, {"relaxationTime": 0},
                          {"comfortDistance": -.1}, {"obstacleStrength": math.inf},
                          {"interactionLambda": -1}, {"interactionN": "1"},
                          {"interactionNPrime": math.nan}, {"interactionRange": 0},
                          {"maxSpeedFactor": False}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                UserModel(overrides)

    def test_force_mode_does_not_change_default_initial_population_or_rng(self):
        manuscript = engine(30)
        legacy = engine(30, {"socialForceMode": "legacy"})
        self.assertEqual(manuscript.agents, legacy.agents)
        self.assertEqual((manuscript.rng.s, manuscript.rng.spare), (legacy.rng.s, legacy.rng.spare))


if __name__ == "__main__":
    unittest.main()
