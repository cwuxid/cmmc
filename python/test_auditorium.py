"""Run: python -m unittest -v test_auditorium.py"""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import unittest

from auditorium import (
    Building, GeometryConfig, Observation, Random, Simulation, SimulationConfig,
    WEIGHT_NAMES, recommended_size,
)
from run_simulation import main, project_output


class ModelTests(unittest.TestCase):
    # These tests check model invariants and reference outcomes, not whether the
    # behavioral assumptions accurately describe a real evacuation dataset.
    def validate_state(self, sim):
        # Shared consistency checks run throughout movement tests, not only at exit.
        occupied = set()
        exited = 0
        for a in sim.agents:
            self.assertTrue(sim.building.walkable[a.cell])
            # An active tick must be accounted for exactly once: move or wait.
            self.assertEqual(a.moves + a.wait_steps, a.exit_time if a.exited else sim.time)
            if a.exited:
                exited += 1
                self.assertEqual(sim.building.exit_at[a.cell], a.exit_id)
            else:
                self.assertNotIn(a.cell, occupied)
                occupied.add(a.cell)
                self.assertEqual(sim.occupancy[a.cell], a.id)
                self.assertEqual(sim.building.exit_at[a.cell], -1)
        self.assertEqual(exited, sim.exited_count)
        self.assertEqual(len(occupied) + exited, len(sim.agents))

    def test_weight_distribution_and_negative_draws(self):
        # A large fixed-seed sample checks variance versus standard deviation and
        # catches clipping. Finite samples need tolerances, not an exact mean of 0.5.
        sim = Simulation({"participants": 800})
        values = [a.weights[k] for a in sim.agents for k in WEIGHT_NAMES]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        self.assertAlmostEqual(mean, 0.5, delta=0.06)
        self.assertAlmostEqual(variance, 1, delta=0.1)
        self.assertTrue(any(x < 0 for x in values))
        self.assertTrue(any(x > 1 for x in values))

    def test_reproducibility(self):
        # Identical seeds/configurations should reproduce the entire exported run.
        first = Simulation({"participants": 40, "seed": 33})
        second = Simulation({"participants": 40, "seed": 33})
        first.run(); second.run()
        self.assertEqual(first.export(), second.export())
        self.assertNotEqual(first.agents[0].weights, Simulation({"participants": 40, "seed": 34}).agents[0].weights)

    def test_zero_participants(self):
        # An empty experiment is complete immediately, without a spurious time tick.
        sim = Simulation({"participants": 0})
        self.assertTrue(sim.complete)
        self.assertFalse(sim.step())
        self.assertEqual(sim.run()["clearanceTime"], 0)

    def test_default_run_and_javascript_reference(self):
        # The fixture guards against unintended changes in formulas or draw order.
        # Agreement across implementations is a regression check, not calibration.
        sim = Simulation()
        summary = sim.run()
        self.validate_state(sim)
        self.assertTrue(sim.complete)
        reference = json.loads(Path(__file__).with_name("python-reference.json").read_text(encoding="utf-8"))
        for key, value in reference["defaultSummary"].items():
            if type(value) is float:
                self.assertAlmostEqual(summary[key], value, places=9, msg=key)
            else:
                self.assertEqual(summary[key], value, key)

    def test_initialization_matches_javascript(self):
        # Check initial draws separately to distinguish sampling changes from later
        # movement/decision changes if the full-run comparison fails.
        sim = Simulation()
        reference = json.loads(Path(__file__).with_name("python-reference.json").read_text(encoding="utf-8"))
        for a, expected in zip(sim.agents, reference["firstAgents"]):
            self.assertEqual(a.initial_cell, expected["initialCell"])
            self.assertEqual(a.entrance_exit, expected["entranceExit"])
            for key in WEIGHT_NAMES:
                self.assertAlmostEqual(a.weights[key], expected["weights"][key], places=12)
            self.assertAlmostEqual(a.beta_distance, expected["betaDistance"], places=12)
            self.assertAlmostEqual(a.beta_congestion, expected["betaCongestion"], places=12)
            self.assertAlmostEqual(a.panic_susceptibility, expected["panicSusceptibility"], places=12)

    def test_movement_capacity_and_conservation_every_step(self):
        # A crowded room exercises contested requests. Save pre-step occupancy to
        # verify the conservative rule against entering a newly vacated cell.
        sim = Simulation({"participants": 90, "seed": 8, "max_steps": 800, "geometry": {"size": 15}})
        while not sim.finished:
            before = [(a.cell, a.exited) for a in sim.agents]
            old_counts = sim.exit_counts.copy()
            occupied = {cell for cell, exited in before if not exited}
            sim.step()
            self.validate_state(sim)
            for a, (cell, exited) in zip(sim.agents, before):
                if exited or a.cell == cell:
                    continue
                x, y = sim.building.position(cell)
                u, v = sim.building.position(a.cell)
                self.assertEqual(abs(x - u) + abs(y - v), 1)
                self.assertNotIn(a.cell, occupied)
            for k, count in enumerate(sim.exit_counts):
                self.assertLessEqual(count - old_counts[k], len(sim.building.exits[k]["cells"]))
        self.assertGreater(sim.conflicts, 0)

    def test_utility_arithmetic_and_congestion_direction(self):
        # Remove residual noise and most weights to isolate arithmetic. At the
        # center, all distances tie, so congestion direction can be checked directly.
        sim = Simulation({"participants": 1, "residual_std": 0})
        a = sim.agents[0]
        a.cell = sim.building.index(15, 15)
        a.weights = dict(time=1, habit=0, peer=0, norm=0, switching=0)
        observation = Observation([0, 1, 2, 3], [], [-1])
        a.beta_congestion = 1
        values = sim.evaluate(a, observation, -1)
        self.assertEqual(values[0]["features"]["congestion"], 0)
        self.assertEqual(values[3]["features"]["congestion"], 1)
        for value in values:
            feature = value["features"]
            self.assertEqual(feature["distance"], 1)
            self.assertAlmostEqual(value["utility"], 1 + feature["congestion"] - feature["time"])
        a.beta_congestion = -1
        values = sim.evaluate(a, observation, -1)
        self.assertEqual(values[0]["features"]["congestion"], 1)
        self.assertEqual(values[3]["features"]["congestion"], 0)

    def test_previous_targets_are_used_for_all_observations(self):
        # Mutate a live target after observing; the saved snapshot must still drive
        # norm calculations, avoiding an advantage from sequential update order.
        sim = Simulation({"participants": 2, "residual_std": 0})
        a, other = sim.agents
        a.cell = sim.building.index(15, 16)
        other.cell = sim.building.index(15, 15)
        other.wait_steps, other.target = 5, 0
        observation = sim.observe(a, sim._make_occupancy(), [-1, 0])
        other.target = 1
        values = sim.evaluate(a, observation, -1)
        self.assertEqual(values[0]["features"]["norm"], 1)
        self.assertEqual(values[1]["features"]["norm"], 0)

    def test_obstacles(self):
        # The blocked rectangle must remain empty while navigation routes around it.
        sim = Simulation({"participants": 40, "seed": 7, "geometry": {"size": 21,
                         "obstacles": [{"x": 9, "y": 5, "width": 3, "height": 11}]}})
        self.assertFalse(sim.building.walkable[sim.building.index(10, 10)])
        while not sim.finished:
            sim.step()
            self.validate_state(sim)
        self.assertTrue(sim.complete)

    def test_custom_exits_and_width(self):
        # Explicit doors replace the defaults. Wider doors expose multiple cells.
        sim = Simulation({"participants": 15, "geometry": {"size": 11, "exits": [
            {"name": "Door", "cells": [{"x": 4, "y": 0}, {"x": 5, "y": 0}]}]}})
        sim.run()
        self.validate_state(sim)
        self.assertEqual(sim.exit_counts, [15])
        wide = Building(GeometryConfig(size=11, exit_width=3))
        self.assertTrue(all(len(e["cells"]) == 3 for e in wide.exits))

    def test_step_limit_is_not_clearance(self):
        # A censored experiment must report remaining people and no clearance time.
        sim = Simulation({"max_steps": 1})
        summary = sim.run()
        self.assertEqual(summary["status"], "step_limit")
        self.assertIsNone(summary["clearanceTime"])
        self.assertGreater(summary["remaining"], 0)
        self.assertFalse(sim.step())

    def test_invalid_configs(self):
        # Include invalid scalar inputs and a geometrically isolated interior cell.
        cases = [
            {"participants": -1}, {"participants": 26, "geometry": {"size": 7}},
            {"weight_variance": -1}, {"seed": True}, {"max_steps": 0},
            {"weight_mean": math.nan}, {"exploration_probability": 2},
            {"geometry": {"size": 7, "exit_width": 6}},
            {"geometry": {"exits": []}}, {"geometry": {"size": 9, "exits": [
                {"name": "Corner", "cells": [{"x": 0, "y": 0}]}]}},
            {"geometry": {"size": 9, "obstacles": [{"x": 2, "y": 2, "width": 99, "height": 1}]}},
            {"geometry": {"size": 9, "obstacles": [
                {"x": 3, "y": 3, "width": 3, "height": 1}, {"x": 3, "y": 5, "width": 3, "height": 1},
                {"x": 3, "y": 4, "width": 1, "height": 1}, {"x": 5, "y": 4, "width": 1, "height": 1}]}},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                Simulation(case)

    def test_config_compatibility_and_no_mutation(self):
        # Shared camelCase JSON must round-trip, while caller-owned objects stay
        # independent of the simulation's copied configuration.
        data = {"maxSteps": 12, "weightVariance": 1, "geometry": {"size": 11, "exitWidth": 2}}
        before = copy.deepcopy(data)
        config = SimulationConfig.from_dict(data)
        self.assertEqual(config.max_steps, 12)
        self.assertEqual(config.geometry.exit_width, 2)
        self.assertEqual(SimulationConfig.from_dict(config.to_dict()), config)
        self.assertEqual(data, before)
        config = SimulationConfig(participants=2)
        sim = Simulation(config)
        config.geometry.size = 99
        self.assertEqual(sim.building.size, 31)
        with self.assertRaises(ValueError):
            SimulationConfig.from_dict({"maxStpes": 123})

    def test_exports_are_strict_json_and_detached(self):
        # Export consumers may edit data freely without mutating the live engine.
        sim = Simulation({"participants": 5})
        snapshot = sim.export()
        json.dumps(snapshot, allow_nan=False)
        snapshot["history"][0]["exited"] = 99
        snapshot["agents"][0]["weights"]["time"] = 99
        self.assertEqual(sim.history[0]["exited"], 0)
        self.assertNotEqual(sim.agents[0].weights["time"], 99)

    def test_zero_variance_and_size_recommendation(self):
        # Degenerate Gaussian weights should be exact; automatic sizing must honor
        # its occupancy target before obstacle area is removed.
        self.assertEqual(Random(42).normal(0.5, 0), 0.5)
        sim = Simulation({"participants": 5, "weight_variance": 0})
        self.assertTrue(all(w == 0.5 for a in sim.agents for w in a.weights.values()))
        side = recommended_size(1000)
        self.assertEqual(side % 2, 1)
        self.assertLessEqual(1000 / (side - 2) ** 2, 0.3)
        self.assertEqual(recommended_size(0), 31)

    def test_cli_headless_and_output_boundaries(self):
        # Invoke main() directly and capture stdout to check the public runner
        # without launching a subprocess or creating files outside the workspace.
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["--n", "5", "--size", "11", "--seed", "11"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["exited"], 5)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--n", "150", "--max-steps", "1"]), 2)
        with self.assertRaises(ValueError):
            project_output("../outside.json")
        with self.assertRaises(ValueError):
            project_output("auditorium.py")


if __name__ == "__main__":
    unittest.main()
