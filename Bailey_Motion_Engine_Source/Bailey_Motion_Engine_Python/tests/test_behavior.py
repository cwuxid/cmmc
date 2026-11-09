"""Manuscript examples and behavioral/observation integration regressions."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bailey_motion import BaileyEngine, UserModel, default_config
from bailey_motion import behavior, geometry as G, perception
from bailey_motion.config import validate_config
from bailey_motion.records import Record, record


def engine(n=3, settings=None):
    w = default_config()
    w.population = n
    return BaileyEngine(w, UserModel({"behavioralOnly": True, **(settings or {})}))


def place(e, a, x=0., y=38., region="foyer", floor=0, zone=None):
    e._index_remove(a)
    e.policy.local.clear_target(a)
    a.update(x=x, y=y, vx=0., vy=0., floor=floor, region=region, zone=zone,
             planId="main" if floor == 0 else "balcony")
    a.params.reaction = 0.
    a.data.started = True
    e._index_add(a)
    e.policy.local.snapshot_tick = None


def commit(e, a, identity):
    action = e.policy.local.action(a, e.context(a), e.portal_map[identity])
    e.policy.local.commit(a, e.context(a), action)
    return action


class BehaviorTests(unittest.TestCase):
    def test_manuscript_examples_with_familiarity_removed(self):
        left = Record(T=1., P=.2, N=1., C=1.)
        right = Record(T=2., P=.8, N=0., C=0.)
        examples = [("A12", (1, 0, 0, 0), -1, -2),
                    ("A13_no_habit_bonus", (1, 0, 0, 0), -1, -2),
                    ("A14", (1, 2, 0, 0), -.6, -.4),
                    ("A15", (1, 0, 1.5, 0), -2.5, -2),
                    ("A16", (1, 0, 0, 1.5), -2.5, -2),
                    ("B07", (1, .5, .8, .3), -2, -1.6)]
        for name, values, ul, ur in examples:
            with self.subTest(name=name):
                weights = Record(zip(("T", "P", "N", "S"), values))
                self.assertAlmostEqual(behavior.behavioral_utility(weights, left), ul)
                self.assertAlmostEqual(behavior.behavioral_utility(weights, right), ur)

    def test_reconstructed_arrival_paths_end_at_each_seat_section(self):
        e = engine(30)
        self.assertEqual({a.seat.section for a in e.agents}, {"orchestra", "loge", "balcony"})
        for a in e.agents:
            m = a.data.arrivalMemory
            self.assertEqual(m.source, "reconstructed")
            self.assertEqual(m.portals[0], "M2")
            self.assertEqual(m.seatLabel, a.seat.label)
            self.assertIn(m.rowSide, m.knownTargets)
            if a.seat.section == "orchestra": self.assertTrue(m.portals[-1].startswith("ACCESS"))
            if a.seat.section == "balcony": self.assertTrue(m.portals[-1].startswith("BACK_"))

    def test_recorded_arrival_route_retains_knowledge_without_utility_bonus(self):
        first = engine(1)
        original = first.agents[0]
        w = default_config(); w.population = 1
        m = copy.deepcopy(original.data.arrivalMemory)
        m.portals[0] = "M0"
        w.arrival.routesBySeat[original.seat.label] = Record(portals=m.portals, rowSide=m.rowSide)
        e = BaileyEngine(w, UserModel())
        a = e.agents[0]
        self.assertEqual(a.data.arrivalMemory.source, "recorded")
        place(e, a)
        f0 = e.policy.local.features(a, e.context(a), e.policy.local.action(a, e.context(a), e.portal_map['M0']))
        f2 = e.policy.local.features(a, e.context(a), e.policy.local.action(a, e.context(a), e.portal_map['M2']))
        self.assertIn('M0', a.data.arrivalMemory.knownTargets)
        self.assertNotIn('H', f0)
        self.assertNotIn('H', f2)
        a.data.arrivalMemory.knownTargets = ['M2']
        self.assertEqual(f0, e.policy.local.features(a, e.context(a), e.policy.local.action(a, e.context(a), e.portal_map['M0'])))

    def test_invalid_arrival_route_rejected(self):
        a = engine(1).agents[0]
        for entry in (Record(portals=["M2", "AUD0"]), Record(portals=["ADA_W"]), Record(portals=["MISSING"]), "bad"):
            w = default_config(); w.population = 1
            w.arrival.routesBySeat[a.seat.label] = entry
            with self.subTest(entry=entry), self.assertRaises(ValueError): BaileyEngine(w, UserModel())
        w.arrival.routesBySeat = {"UNKNOWN_SEAT": Record(portals=["M2"])}
        with self.assertRaises(ValueError): validate_config(w)

    def test_vision_distance_angle_floor_and_explicit_wall(self):
        e = engine(1)
        a = e.agents[0]
        place(e, a)
        a.data.heading = Record(x=1., y=0.)
        settings = e.policy.settings
        settings.fieldOfViewDegrees = 90
        self.assertTrue(perception.visible(a, Record(x=2., y=38., floor=0), e.context(a), settings))
        self.assertFalse(perception.visible(a, Record(x=-2., y=38., floor=0), e.context(a), settings))
        self.assertFalse(perception.visible(a, Record(x=20., y=38., floor=0), e.context(a), settings))
        self.assertFalse(perception.visible(a, Record(x=2., y=38., floor=1), e.context(a), settings))
        e.g.visibilityWalls = [Record(floor=0, start=Record(x=1., y=37.), end=Record(x=1., y=39.))]
        self.assertFalse(perception.visible(a, Record(x=2., y=38., floor=0), e.context(a), settings))

    def test_barrier_and_auditorium_wall_occlude_except_at_openings(self):
        e = engine(1); a = e.agents[0]
        for theta, clear in ((1.5, False), (e.portal_map['ACCESS3'].angle, True)):
            place(e, a, **G.point(16., theta, e.g), region="aisle", zone="orchestra")
            target = G.point(17.7, theta, e.g)
            self.assertEqual(perception.line_of_sight(a, target, e.g, e.portals), clear)
        for theta, clear in ((.3, False), (e.portal_map['AUD0'].angle, True)):
            place(e, a, **G.point(23.6, theta, e.g), region="rim", zone="loge")
            target = G.point(24.5, theta, e.g)
            self.assertEqual(perception.line_of_sight(a, target, e.g, e.portals), clear)
        e.portal_map['AUD0'].enabled = False
        self.assertFalse(perception.line_of_sight(a, target, e.g, e.portals))

    def test_foyer_wall_occludes_and_open_door_transmits_sight(self):
        e = engine(1); a = e.agents[0]
        place(e, a, x=0., y=33.)
        self.assertTrue(perception.line_of_sight(a, Record(x=0., y=31.8), e.g, e.portals))
        e.portal_map['F1'].enabled = False
        self.assertFalse(perception.line_of_sight(a, Record(x=0., y=31.8), e.g, e.portals))
        self.assertFalse(perception.line_of_sight(a, Record(x=10., y=31.8), e.g, e.portals))

    def test_unseen_unknown_actions_excluded_but_route_memory_retained(self):
        e = engine(1, {"visionRange": .1})
        a = e.agents[0]; place(e, a)
        actions = e.policy.local.perceived_actions(a, e.context(a))
        self.assertEqual([o.id for o in actions], ['M2'])
        self.assertEqual(actions[0].perception, 'remembered')

    def test_local_search_does_not_use_hidden_door_locations(self):
        e = engine(1, {"visionRange": .1})
        a = e.agents[0]
        place(e, a, **G.point(25.5, 1., e.g), region='corridor')
        a.data.arrivalMemory.knownTargets = []
        actions = e.policy.local.perceived_actions(a, e.context(a))
        self.assertEqual({o.id for o in actions}, {'SEARCH_LEFT', 'SEARCH_RIGHT'})
        self.assertTrue(all(o.kind == 'search' for o in actions))

    def test_peer_share_uses_direction_even_for_different_target_ids(self):
        e = engine(2)
        a, b = e.agents
        place(e, a, x=0., y=37.5); place(e, b, x=0., y=38.)
        action = commit(e, a, 'M2'); commit(e, b, 'M1')
        e.policy.local.before_tick(e.context())
        f = e.policy.local.features(a, e.context(a), action)
        self.assertEqual(f.P, 1.)
        self.assertNotEqual(a.data.targetId, b.data.targetId)

    def test_unseen_or_other_floor_people_do_not_enter_peer_share(self):
        e = engine(3)
        a, b, c = e.agents
        place(e, a, x=-1., y=38.); place(e, b, x=1., y=38.)
        place(e, c, x=-1., y=38., floor=1)
        action = commit(e, a, 'M2'); commit(e, b, 'M2')
        e.g.visibilityWalls = [Record(floor=0, start=Record(x=0., y=37.), end=Record(x=0., y=39.))]
        e.policy.local.before_tick(e.context())
        self.assertEqual(e.policy.local.features(a, e.context(a), action).observedPeople, 0)

    def test_behavior_observations_are_frozen_within_tick(self):
        e = engine(2)
        a, b = e.agents
        place(e, a); place(e, b, y=39.)
        action = commit(e, a, 'M2'); commit(e, b, 'M2')
        e.policy.local.before_tick(e.context())
        before = e.policy.local.features(a, e.context(a), action)
        b.update(x=100., y=100., vx=-1.)
        after = e.policy.local.features(a, e.context(a), action)
        self.assertEqual(before, after)

    def test_stationary_queue_cutting_is_penalized(self):
        e = engine(2)
        a, b = e.agents
        place(e, a, y=40.2); place(e, b, y=39.3)
        commit(e, a, 'M0'); commit(e, b, 'M2')
        e.policy.local.before_tick(e.context())
        action = e.policy.local.action(a, e.context(a), e.portal_map['M2'])
        f = e.policy.local.features(a, e.context(a), action, current_id='M0')
        self.assertEqual(f.counterflow, 0.)
        self.assertEqual(f.queueCut, 1.)
        self.assertEqual(f.N, 1.)
        self.assertEqual(f.C, 1.)

    def test_queue_delay_uses_visible_people_ahead_and_can_be_disabled(self):
        e = engine(2)
        a, b = e.agents
        place(e, a, y=37.5); place(e, b, y=39.8)
        action = commit(e, a, 'M2'); commit(e, b, 'M2')
        e.policy.local.before_tick(e.context())
        f = e.policy.local.features(a, e.context(a), action)
        self.assertEqual(f.queuePeopleAhead, 1)
        self.assertAlmostEqual(f.queueSeconds, 1 / (1.75 * 1.3))
        self.assertEqual(f.queueCut, 0.)
        e.policy.settings.perceivedQueueDelay = False
        self.assertEqual(e.policy.local.features(a, e.context(a), action).queueSeconds, 0.)

    def test_staying_in_existing_queue_does_not_count_as_abandonment(self):
        e = engine(2)
        a, b = e.agents
        place(e, a, y=40.2); place(e, b, y=39.3)
        action = commit(e, a, 'M2'); commit(e, b, 'M2')
        a.data.queueSince = 0.; b.data.queueSince = 1.
        e.t = 2.; e.policy.local.before_tick(e.context())
        f = e.policy.local.features(a, e.context(a), action, current_id='M2')
        self.assertEqual((f.C, f.queueCut), (0., 0.))

    def test_first_row_choice_is_utility_based_instead_of_nearest(self):
        e = engine(1)
        a = e.agents[0]; a.params.reaction = 0.
        actions = e.policy.local.available_actions(a, e.context(a))
        far = max(actions, key=lambda o:o.distance)
        direction = e.policy.local.direction(a, e.context(a), far)
        e.policy.local.observed = lambda a, api: [Record(intent=direction, vx=0., vy=0., queueTarget=None, region='aisle')]
        a.data.weights = Record(T=1., P=100., N=0., S=0.)
        e.policy.decide(a, e.context(a))
        self.assertEqual(a.data.targetId, far.id)

    def test_foyer_entry_selection_is_utility_based_and_local(self):
        e = engine(1)
        a = e.agents[0]
        place(e, a, **G.point(25.5, e.portal_map['F0'].angle, e.g), region='corridor')
        a.data.weights = Record(T=1., P=0., N=0., S=100.)
        commit(e, a, 'F2')
        e.policy.route_from_corridor(a, e.context(a))
        self.assertEqual(a.data.targetId, 'F2')
        self.assertIsNone(a.data.exitChoice)
        self.assertNotIn('MAIN', [o.id for o in e.policy.local.available_actions(a, e.context(a))])

    def test_legacy_main_route_cannot_pick_side_exit_in_current_geometry(self):
        e = engine(1, {'behaviorMode': 'legacy'})
        a = e.agents[0]
        place(e, a, **G.point(26.6, e.portal_map['SIDE_E1'].angle, e.g), region='corridor')
        e.policy.pick_exit = lambda a, api: 'MAIN'
        e.policy.route_from_corridor(a, e.context(a))
        self.assertIn(a.data.portal, ('F0', 'F1', 'F2'))

    def test_global_commitment_counts_do_not_change_local_utility(self):
        e = engine(1)
        a = e.agents[0]; place(e, a)
        options = e.policy.local.perceived_actions(a, e.context(a))
        e.policy.choose(a, e.context(a), options, 'portal')
        before = record(a.data.lastDecision)
        e.policy._counts = {o.id:10000 * i for i, o in enumerate(options)}
        e.policy.choose(a, e.context(a), options, 'portal')
        self.assertEqual(before, a.data.lastDecision)
        self.assertEqual(a.data.lastDecision.globalCrowdTerm, 0.)

    def test_every_decision_region_honors_one_or_three_second_interval(self):
        e = engine(1, {'decisionInterval':1})
        a = e.agents[0]
        cases = [('foyer', None, 0., 38., 0),
                 ('row', a.seat.section, a.seat.x, a.seat.y, a.seat.floor),
                 ('aisle', 'loge', *G.point(20., a.aisleAngle, e.g).values(), 0),
                 ('rim', 'loge', *G.point(23.15, 1.5, e.g).values(), 0),
                 ('corridor', None, *G.point(25.5, 1.5, e.g).values(), 0),
                 ('balcony-rim', 'balcony', *G.point(23.15, 1.5, e.g).values(), 1),
                 ('stage-east', None, 22., 5.3, 0)]
        for interval, (region, zone, x, y, floor) in ((interval, case) for interval in (1, 3) for case in cases):
            with self.subTest(region=region, interval=interval):
                e.policy.settings.decisionInterval = interval
                place(e, a, x=x, y=y, region=region, floor=floor, zone=zone)
                e.t = .1; e.tick += 1
                e.policy.decide(a, e.context(a))
                self.assertAlmostEqual(a.data.lastDecision.time, .1)
                e.t = .9
                e.policy.decide(a, e.context(a))
                self.assertAlmostEqual(a.data.lastDecision.time, .1)
                e.t = interval + .1; e.tick += 1
                e.policy.decide(a, e.context(a))
                self.assertAlmostEqual(a.data.lastDecision.time, interval + .1)

    def test_stage_transition_resets_target_and_switching_cost(self):
        e = engine(1)
        a = e.agents[0]; place(e, a)
        commit(e, a, 'M0')
        e.policy.local.clear_target(a)
        e.policy.decide(a, e.context(a))
        self.assertTrue(all(o.features.C == 0. for o in a.data.lastDecision.alternatives))

    def test_new_door_target_retreats_from_wrong_apron_before_traversing(self):
        e = engine(1)
        a = e.agents[0]
        place(e, a, x=1.688473580647598, y=41.10769300660089)
        commit(e, a, 'M2')
        a.data.nextDecision = 1e9
        goal = e.policy.goal(a, e.context(a))
        self.assertAlmostEqual(goal.x, a.x)
        self.assertLess(goal.y, e.g.regions.foyer.maxY - a.radius)
        e.run_steps(150)
        self.assertTrue(a.exited)
        self.assertEqual(a.exitThreshold.portalId, 'M2')

    def test_opposing_row_pair_can_reconsider_observed_blockage(self):
        e = engine(2)
        seat = next(s for s in e.seats if s.section == 'balcony' and s.row == 7 and s.block == 1)
        for a, theta, values, identity in (
                (e.agents[0], .16, (.326, .495, .113, 9.22), 'ROW_RIGHT'),
                (e.agents[1], .18, (2.038, .352, .283, 1.511), 'ROW_LEFT')):
            a.seat = record(seat)
            place(e, a, **G.point(seat.r, theta, e.g), region='row', floor=1, zone='balcony')
            a.data.arrivalMemory.knownTargets = ['ROW_RIGHT', 'M2', 'BACK_E']
            a.data.weights = Record(zip(('T','P','N','S'), values))
            action = next(o for o in e.policy.local.available_actions(a, e.context(a)) if o.id == identity)
            e.policy.local.commit(a, e.context(a), action)
        weights = [record(a.data.weights) for a in e.agents]
        e.run_steps(400)
        self.assertTrue(all(a.region != 'row' for a in e.agents))
        self.assertEqual(weights, [a.data.weights for a in e.agents])

    def test_row_block_wait_is_directional_observable_and_optional(self):
        e = engine(2)
        a, b = e.agents
        seat = record(a.seat)
        for body, theta, identity in ((a, seat.angle, 'ROW_RIGHT'), (b, seat.angle + .03, 'ROW_LEFT')):
            body.seat = record(seat)
            place(e, body, **G.point(seat.r, theta, e.g), region='row', zone=seat.section, floor=seat.floor)
            action = next(o for o in e.policy.local.available_actions(body, e.context(body)) if o.id == identity)
            e.policy.local.commit(body, e.context(body), action)
        a.blockedTicks = 5
        e.t = 10.; e.policy.local.before_tick(e.context())
        options = e.policy.local.available_actions(a, e.context(a))
        right = next(o for o in options if o.id == 'ROW_RIGHT')
        left = next(o for o in options if o.id == 'ROW_LEFT')
        initial = e.policy.local.features(a, e.context(a), right)
        e.t = 20.
        later = e.policy.local.features(a, e.context(a), right)
        self.assertGreater(later.rowBlockedSeconds, initial.rowBlockedSeconds)
        self.assertEqual(e.policy.local.features(a, e.context(a), left).rowBlockedSeconds, 0.)
        e.policy.settings.perceivedQueueDelay = False
        self.assertEqual(e.policy.local.features(a, e.context(a), right).rowBlockedSeconds, 0.)

    def test_features_do_not_depend_on_utility_weights_and_seed_repeats(self):
        first, second = engine(12), engine(12)
        a = first.agents[0]
        action = first.policy.local.available_actions(a, first.context(a))[0]
        original = first.policy.local.features(a, first.context(a), action)
        weights = record(a.data.weights)
        a.data.weights = Record(T=100., P=.1, N=.1, S=.1)
        self.assertEqual(original, first.policy.local.features(a, first.context(a), action))
        a.data.weights = weights
        first.run_steps(100); second.run_steps(100)
        self.assertEqual(first.export(), second.export())

    def test_new_settings_and_visibility_walls_are_validated(self):
        for overrides in ({'decisionInterval':0}, {'timeScale':0}, {'observeRadius':0},
                          {'visionRange':-1}, {'fieldOfViewDegrees':361}, {'peerDirectionToleranceDegrees':0},
                          {'queueSpeedThreshold':math.inf}, {'perceivedQueueDelay':'yes'},
                          {'behavioralOnly':1}, {'behaviorMode':'unknown'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError): UserModel(overrides)
        w = default_config()
        w.geometry.visibilityWalls = [Record(floor=0, start=Record(x=0., y=0.), end=Record(x=0., y=0.))]
        with self.assertRaises(ValueError): validate_config(w)

    def test_weights_stay_fixed_and_full_diagnostics_export(self):
        e = engine(30, {'behavioralOnly':False})
        weights = [record(a.data.weights) for a in e.agents]
        e.run_steps(150)
        self.assertEqual(weights, [a.data.weights for a in e.agents])
        decisions = [a.data.lastDecision for a in e.agents if 'lastDecision' in a.data]
        self.assertTrue(decisions)
        for d in decisions:
            winner = max(d.alternatives, key=lambda o:o.utility)
            self.assertEqual(d.chosen, winner.id)
            for o in d.alternatives:
                self.assertAlmostEqual(o.utility, o.behavioral + o.distance + o.panic + o.residual)
        json.dumps(e.export(), allow_nan=False)


if __name__ == '__main__': unittest.main()
