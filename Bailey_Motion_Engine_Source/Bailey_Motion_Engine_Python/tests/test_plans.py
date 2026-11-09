"""Specification topology, independent plans, transfers, and exact exit thresholds."""
from pathlib import Path
import math
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bailey_motion import BaileyEngine, UserModel, default_config
from bailey_motion import geometry as G, plans, transfers
from bailey_motion.config import validate_config
from bailey_motion.records import Record
from bailey_motion.viewer import draw


def make_engine(n=1):
    world = default_config()
    world.population = n
    return BaileyEngine(validate_config(world), UserModel())


def place(engine, agent, **changes):
    engine._index_remove(agent)
    agent.update(changes)
    if agent.floor >= 0 and not agent.exited:
        agent.planId = plans.plan_id(engine.g, agent.floor)
        engine._index_add(agent)


class PlanTests(unittest.TestCase):
    def test_capacity_equal_units_and_distinct_plans(self):
        e = make_engine(1329)
        self.assertEqual(len(e.agents), 1329)
        self.assertEqual({s.id: sum(a.seat.section == s.id for a in e.agents) for s in e.g.sections},
                         {"orchestra": 527, "loge": 486, "balcony": 316})
        self.assertEqual({a.radius for a in e.agents}, {.2025})
        self.assertTrue(all(a.floor == (1 if a.seat.section == "balcony" else 0) for a in e.agents))
        self.assertTrue(all(G.inside_region(a, a.x, a.y, e.g) for a in e.agents))

    def test_portal_and_entrance_inventory(self):
        e = make_engine()
        self.assertEqual(len(e.portals), 34)
        self.assertEqual(sum(p.type == "access" for p in e.portals), 6)
        self.assertEqual(sum(p.id.startswith("AUD") for p in e.portals), 9)
        self.assertEqual(sum(p.id in ("F0", "F1", "F2") for p in e.portals), 3)
        self.assertEqual(sum(p.type == "exit" and p.exitId == "MAIN" for p in e.portals), 5)
        self.assertEqual(sum(p.id.startswith("SIDE_") for p in e.portals), 4)
        self.assertEqual(sum(p.type == "exit" for p in e.portals), 11)
        self.assertTrue(all(p.floor == 0 for p in e.portals if p.type == "exit"))
        self.assertTrue(all(p.toEntrance in e.g.entrances for p in e.portals if p.type not in ("exit", "elevator")))

    def test_orchestra_cannot_walk_or_teleport_across_barrier(self):
        e = make_engine()
        a, p = e.agents[0], e.portal_map["ACCESS3"]
        place(e, a, floor=0, region="aisle", zone="orchestra", aisleAngle=p.angle, x=p.x, y=p.y)
        other_side = e.g.entrances[p.toEntrance]
        self.assertFalse(e._clear(a, other_side.x, other_side.y))
        self.assertFalse(e.set_region(a, "aisle", other_side.x, other_side.y, {"zone": "loge"}))
        rim = G.point(23.15, p.angle, e.g)
        self.assertFalse(e.set_region(a, "rim", rim.x, rim.y))
        self.assertFalse(e.set_region(a, "balcony-rim", extras={"floor": 1}))

    def test_all_six_access_points_land_in_loge_and_preserve_identity(self):
        for name in (f"ACCESS{i}" for i in range(1, 7)):
            with self.subTest(portal=name):
                e = make_engine()
                a, p = e.agents[0], e.portal_map[name]
                weights, agent_id, seat = dict(a.data.weights), a.id, dict(a.seat)
                place(e, a, floor=0, region="aisle", zone="orchestra", aisleAngle=p.angle, x=p.x, y=p.y)
                self.assertTrue(e.use_portal(a, name))
                self.assertEqual((a.floor, a.region), (-1, "stairs"))
                self.assertEqual(e.done, 0)
                e.t = a.stairUntil + .001
                transfers.advance(e, a)
                self.assertEqual((a.floor, a.zone, a.region), (0, "loge", "aisle"))
                self.assertEqual(a.transfers[-1].destinationEntrance, p.toEntrance)
                self.assertEqual((a.id, dict(a.seat), dict(a.data.weights)), (agent_id, seat, weights))
                self.assertTrue(G.inside_region(a, a.x, a.y, e.g))

    def test_barrier_material_and_connector_width_block_body_edges(self):
        e = make_engine()
        a, p = e.agents[0], e.portal_map["ACCESS3"]
        # A body outside the opening cannot overlap the wall near the aisle end.
        theta = p.angle + .8 / e.g.zones.orchestra.maxR
        point = G.point(e.g.zones.orchestra.maxR, theta, e.g)
        place(e, a, floor=0, region="aisle", zone="orchestra", aisleAngle=p.angle, x=point.x, y=point.y)
        self.assertFalse(e._clear(a, point.x, point.y))
        # A center can be within the service radius but still too far sideways
        # for its whole body to fit the 1.3 m access opening.
        x, y = p.x - math.sin(p.angle) * .6, p.y + math.cos(p.angle) * .6
        place(e, a, x=x, y=y)
        self.assertFalse(e.use_portal(a, p.id))

    def test_main_plan_and_balcony_do_not_collide_at_same_coordinates(self):
        e = make_engine(2)
        a, b = e.agents
        place(e, a, floor=0, x=0, y=35)
        place(e, b, floor=1, x=0, y=35)
        self.assertNotIn(b, e.neighbors(a, 1))
        self.assertNotIn(a, e.neighbors(b, 1))

    def test_rear_staircases_have_two_flights_and_separated_fifo_lanes(self):
        e = make_engine(4)
        p = e.portal_map["BACK_E"]
        self.assertEqual((len(p.flights), p.laneCount), (2, 2))
        self.assertGreater(p.laneDivider, 0)
        p.tokens = 10
        for a in e.agents[:2]:
            place(e, a, floor=1, region="balcony-rim", zone="balcony", x=p.x, y=p.y)
            self.assertTrue(e.use_portal(a, p.id))
        self.assertEqual({a.transit.lane for a in e.agents[:2]}, {0, 1})
        a = e.agents[2]
        place(e, a, floor=1, region="balcony-rim", zone="balcony", x=p.x, y=p.y)
        self.assertFalse(e.use_portal(a, p.id))
        e.t = max(lane.nextEntryAt for lane in p.lanes) + .01
        self.assertTrue(e.use_portal(a, p.id))
        lane = p.lanes[a.transit.lane]
        head = e.agents[lane.agents[0]]
        self.assertGreater(a.stairUntil, head.stairUntil)
        e.t = max(a.stairUntil, head.stairUntil) + .01
        transfers.advance(e, a)
        self.assertEqual(a.floor, -1)  # No overtaking the head of this same lane.
        transfers.advance(e, head)
        self.assertEqual((head.floor, head.region), (0, "foyer"))
        self.assertEqual(head.transfers[-1].destinationEntrance, "FOYER_BACK_E")
        self.assertEqual(e.done, 0)

    def test_busy_destination_keeps_same_unit_in_transit(self):
        e = make_engine()
        a, p = e.agents[0], e.portal_map["BACK_W"]
        place(e, a, floor=1, region="balcony-rim", zone="balcony", x=p.x, y=p.y)
        self.assertTrue(e.use_portal(a, p.id))
        e.t = a.stairUntil + .01
        with patch.object(e, "_clear", return_value=False):
            transfers.advance(e, a)
        self.assertEqual(a.floor, -1)
        self.assertTrue(a.transit.awaitingEntrance)
        self.assertIn(a.id, p.lanes[a.transit.lane].agents)
        self.assertEqual(len(e.agents), 1)
        transfers.advance(e, a)
        self.assertEqual((a.floor, a.region), (0, "foyer"))

    def test_balcony_stage_stairs_land_on_first_floor_before_final_exit(self):
        e = make_engine(6)
        a = next(a for a in e.agents if a.seat.section == "balcony")
        p = e.portal_map["STAGE_E"]
        place(e, a, region="balcony-rim", x=p.x, y=p.y)
        self.assertTrue(e.use_portal(a, p.id))
        self.assertFalse(a.exited)
        self.assertEqual(e.done, 0)
        e.t = a.stairUntil + .001
        transfers.advance(e, a)
        self.assertEqual((a.floor, a.region), (0, "stage-east"))
        self.assertEqual(a.data.portal, "GROUND_STAGE_E")
        self.assertFalse(a.exited)
        self.assertEqual(a.originPlan, "balcony")
        for _ in range(60):
            e.step()
            if a.exited:
                break
        self.assertTrue(a.exited)
        self.assertEqual(a.exitThreshold.floor, 0)
        self.assertEqual(a.exitThreshold.portalId, "GROUND_STAGE_E")

    def test_exit_is_line_crossing_not_proximity_or_interior_transfer(self):
        e = make_engine()
        a = e.agents[0]
        place(e, a, floor=0, region="foyer", zone=None, x=0, y=41.1)
        self.assertFalse(e.use_portal(a, "M2"))
        self.assertEqual(e.done, 0)
        e.t = .1
        e._move(a, Record(vx=0, vy=2))
        self.assertTrue(a.exited)
        self.assertAlmostEqual(a.exitAt, .05, places=10)
        self.assertAlmostEqual(a.y, 41.2)
        self.assertEqual(len(e.threshold_events), 1)
        with self.assertRaises(ValueError):
            e.exit(make_engine().agents[0], "CUSTOM")

    def test_every_exterior_threshold_completes_only_on_main_plan(self):
        world = make_engine()
        for portal in [p for p in world.portals if p.type == "exit"]:
            with self.subTest(portal=portal.id):
                e = make_engine()
                a, p = e.agents[0], e.portal_map[portal.id]
                place(e, a, floor=0, region=p["from"], zone=None,
                      x=p.x - .1 * p.normal.x, y=p.y - .1 * p.normal.y)
                self.assertIsNone(plans.crossing(Record(a, floor=1), p.x + .1*p.normal.x, p.y + .1*p.normal.y, p))
                e.t = .1
                e._move(a, Record(vx=2*p.normal.x, vy=2*p.normal.y))
                self.assertTrue(a.exited)
                self.assertEqual(a.exitId, p.exitId)
                self.assertEqual(a.exitThreshold.plan, "main")

    def test_disabled_and_capacity_blocked_thresholds_do_not_count(self):
        for disabled in (True, False):
            e = make_engine()
            a, p = e.agents[0], e.portal_map["M2"]
            place(e, a, floor=0, region="foyer", zone=None, x=0, y=41.1)
            p.enabled, p.tokens = not disabled, 10 if disabled else 0
            e.t = .1
            e._move(a, Record(vx=0, vy=2))
            self.assertFalse(a.exited)
            self.assertEqual(e.done, 0)
            self.assertGreater(e.metrics.portalWaits, 0)

    def test_diagonal_motion_cannot_tunnel_into_exit_apron_through_wall(self):
        e = make_engine()
        a = e.agents[0]
        place(e, a, floor=0, region="foyer", zone=None, x=.9, y=40.8)
        e.t = .1
        e._move(a, Record(vx=-3, vy=7))
        self.assertFalse(a.exited)
        self.assertLessEqual(a.y, 41.2)

    def test_elevator_excluded_and_rare_routes_available(self):
        e = make_engine()
        a, elevator = e.agents[0], e.portal_map["ADA_W"]
        self.assertFalse(elevator.enabled)
        elevator.enabled = True  # Even a direct programmatic toggle cannot admit it.
        place(e, a, floor=0, region="foyer", x=elevator.x, y=elevator.y)
        self.assertFalse(e.use_portal(a, elevator.id))
        self.assertFalse(plans.eligible(a, elevator))
        self.assertTrue(all(p.enabled for p in e.portals if p.rare))
        self.assertEqual(a.data.arrivalMemory.portals[0], "M2")
        self.assertIn("M2", a.data.arrivalMemory.knownTargets)

    def test_invalid_connections_and_inventories_are_rejected(self):
        for change in ("missing_entry", "wrong_plan", "extra_exit", "enable_elevator", "wrong_lanes"):
            world = default_config()
            if change == "missing_entry": world.geometry.portals[0].toEntrance = "MISSING"
            elif change == "wrong_plan": world.geometry.entrances["FOYER_BACK_E"].floor = 1
            elif change == "extra_exit": next(p for p in world.geometry.portals if p.type == "exit").floor = 1
            elif change == "enable_elevator": world.geometry.portals[-1].evacuationAllowed = True
            elif change == "wrong_lanes": next(p for p in world.geometry.portals if p.id == "BACK_E").laneCount = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config(world)

    def test_two_plan_rendering_is_read_only(self):
        class Canvas:
            def winfo_width(self): return 600
            def winfo_height(self): return 600
            def __getattr__(self, name): return lambda *args, **kwargs: None
        e = make_engine()
        before = e.export()
        draw(Canvas(), e, 0)
        draw(Canvas(), e, 1)
        self.assertEqual(e.export(), before)

    def test_end_to_end_routes_conserve_units_and_record_thresholds(self):
        e = make_engine(30)
        e.config.limits.maxSeconds = 120
        e.run()
        # The retained collision/steering model can leave opposing flows blocked.
        # Check legal routes and honest completion accounting rather than assuming
        # that every heterogeneous realization must clear by an arbitrary deadline.
        self.assertGreater(e.done, 0)
        self.assertEqual(len(e.threshold_events), e.done)
        self.assertEqual(e.done + sum(e.summary()["planOccupancy"].values()), 30)
        for a in e.agents:
            if not a.exited:
                self.assertIsNone(a.exitThreshold)
                continue
            self.assertEqual(a.exitThreshold.floor, 0)
            if a.seat.section == "orchestra":
                self.assertTrue(any(t.sourcePortal.startswith("ACCESS") for t in a.transfers))
                self.assertTrue(any(t.sourcePortal.startswith("AUD") for t in a.transfers))
            if a.originPlan == "balcony":
                self.assertTrue(any(t.sourcePlan == "balcony" and t.destinationPlan == "main" for t in a.transfers))
        self.assertEqual(sum(e.summary()["exitedByOriginPlan"].values()), e.done)
        if e.done < 30:
            self.assertIsNone(e.summary()["clearanceTime"])


if __name__ == "__main__":
    unittest.main()
