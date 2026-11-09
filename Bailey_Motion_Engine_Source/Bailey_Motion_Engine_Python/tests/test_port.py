"""Engine, policy, export, and JavaScript-reference regression checks."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Test discovery can run from the workspace root or an isolated interpreter;
# add this port explicitly so the older square-room modules are never imported.
sys.path.insert(0, str(ROOT))
from bailey_motion import BaileyEngine, UserModel, default_config
from bailey_motion.config import legacy_config
from bailey_motion import geometry as G
from bailey_motion.cli import main, output_path
from bailey_motion.config import validate_config
from bailey_motion.loader import compile_policy, default_policy_source
from archived_five_weight_policy import ArchivedUserModel
from bailey_motion.random import RNG
from bailey_motion.records import Record
from bailey_motion.viewer import draw

REFERENCE = json.loads(Path(__file__).with_name("javascript_reference.json").read_text(encoding="utf-8"))
# This fixture records source JavaScript outcomes, not measured evacuation data.


def make_engine(population=12, seed=2026, policy=None):
    # Fresh world/policy instances prevent one test's custom settings from leaking.
    # Keep the original JavaScript parity fixture scoped to its archived geometry.
    # New floor-plan topology is tested separately in test_plans.py.
    config = legacy_config()
    config.population, config.seed = population, seed
    # Five-weight historical policy is confined to test fixtures. Runtime
    # policies now omit familiarity, so their trajectories intentionally differ.
    return BaileyEngine(config, ArchivedUserModel() if policy is None else policy)


def relocate(engine, agent, **changes):
    # Mechanics tests place bodies in controlled scenarios; keep the spatial
    # index synchronized exactly as a legitimate engine transition would.
    engine._index_remove(agent)
    agent.update(changes)
    if agent.floor >= 0 and not agent.exited:
        engine._index_add(agent)


class PortTests(unittest.TestCase):
    def assert_nested(self, actual, expected, path="root"):
        # Compare complete nested state while allowing tiny cross-runtime floating
        # differences. Structural/key/string mismatches still fail directly.
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected), path)
            for key in expected:
                self.assert_nested(actual[key], expected[key], f"{path}.{key}")
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected), path)
            for i, (a, b) in enumerate(zip(actual, expected)):
                self.assert_nested(a, b, f"{path}[{i}]")
        elif type(expected) in (int, float) and type(actual) in (int, float):
            self.assertAlmostEqual(actual, expected, delta=1e-8 + 1e-11 * abs(expected), msg=path)
        else:
            self.assertEqual(actual, expected, path)

    def test_rng_and_distribution_reference(self):
        # Matching both uniform and cached-normal draw order is necessary for
        # every downstream distribution, shuffled update order, and trajectory.
        for seed, expected in REFERENCE["rng"].items():
            rng = RNG(int(seed))
            actual = dict(uniform=[rng.uniform() for _ in range(20)],
                          normal=[rng.normal() for _ in range(20)],
                          beta=[rng.sample(dict(type="beta", mean=.55, sd=.2)) for _ in range(10)],
                          lognormal=[rng.sample(dict(type="lognormal", mean=2, sd=1.2)) for _ in range(10)],
                          shuffle=rng.shuffle(list(range(15))))
            self.assert_nested(actual, expected, f"seed={seed}")

    def test_geometry_inventory_and_regions(self):
        # Exact per-section inventory and legal starting positions are geometry
        # invariants, independent of whether the behavioral policy is realistic.
        e = make_engine()
        counts = {s.id: sum(seat.section == s.id for seat in e.seats) for s in e.g.sections}
        self.assertEqual(counts, {"orchestra": 527, "loge": 486, "balcony": 316})
        self.assertEqual(len(e.portals), 25)
        self.assertTrue(all(G.inside_region(a, a.x, a.y, e.g) for a in e.agents))
        self.assertFalse(G.inside_region(e.agents[0], 1000, 1000, e.g))

    def test_javascript_initialization_and_trajectory_checkpoints(self):
        # Compare full agent/policy state, metrics, portal tokens, and RNG state,
        # not just total exits. Tolerance accommodates transcendental libraries.
        for case in REFERENCE["cases"]:
            e = make_engine(case["population"], case["seed"])
            for expected in case["checkpoints"]:
                with self.subTest(population=case["population"], seed=case["seed"], tick=expected["tick"]):
                    e.run_steps(expected["tick"] - e.tick)
                    actual = dict(t=e.t, tick=e.tick, done=e.done, metrics=e.metrics,
                                  agents=e.agents, portals=e.portals, history=e.history,
                                  rng=dict(s=e.rng.s, spare=e.rng.spare))
                    self.assert_nested(actual, expected)

    def test_repeated_seed_is_deterministic(self):
        # Determinism is expected within Python for identical settings and inputs.
        a, b = make_engine(15, 22), make_engine(15, 22)
        a.run_steps(150)
        b.run_steps(150)
        self.assertEqual(a.export(), b.export())

    def test_correlated_unit_mean_lognormal(self):
        # Check arithmetic mean/positivity in weight space, but covariance in log
        # space. A finite random sample requires tolerances around theoretical values.
        policy, rng = UserModel({"weightSigma": 1.2}), RNG(33)
        api = Record(normal=rng.normal)
        values = [list(policy.sample_weights(api).values()) for _ in range(20000)]
        for j in range(4):
            column = [row[j] for row in values]
            self.assertGreater(min(column), 0)
            self.assertAlmostEqual(sum(column) / len(column), 1, delta=.08)
        logs = [[math.log(x) for x in row] for row in values]
        means = [sum(row[j] for row in logs) / len(logs) for j in range(4)]
        for j in range(4):
            self.assertAlmostEqual(means[j], -.72, delta=.035)
            for k in range(4):
                covariance = sum((row[j] - means[j]) * (row[k] - means[k]) for row in logs) / len(logs)
                self.assertAlmostEqual(covariance, 1.44 if j == k else -.216, delta=.065)
        self.assertTrue(any(max(row) > 10 for row in values))

    def test_invalid_weight_covariance(self):
        # Equicorrelation endpoints make the four-dimensional covariance singular.
        for rho in (-1 / 3, 1, -1):
            with self.subTest(rho=rho), self.assertRaises(ValueError):
                make_engine(1, policy=UserModel(dict(weightRho=rho)))

    def test_reaction_time_delays_policy_start(self):
        # Before reaction time, the policy requests zero velocity and has not started.
        e = make_engine(1)
        a = e.agents[0]
        a.params.reaction = 100
        e.run_steps(5)
        self.assertFalse(a.data.started)
        self.assertEqual((a.vx, a.vy), (0, 0))

    def test_source_row_choice_and_missing_familiarity_are_preserved(self):
        # Guard retained source quirks so a future behavioral fix is an explicit
        # model revision rather than an accidental consequence of translation.
        e = make_engine(10)
        for a in e.agents:
            s = a.seat
            nearest = "ROW_LEFT" if s.r * (s.angle - s.leftAisle) <= s.r * (s.rightAisle - s.angle) else "ROW_RIGHT"
            self.assertEqual(a.data.rowSideChoice, nearest)
            self.assertNotIn("familiarBuildingExit", a.data)

    def test_noise_is_cached_by_option_kind_and_window(self):
        # Repeated scoring within one bucket must reuse noise without drawing again.
        e = make_engine(1)
        a, api = e.agents[0], e.context(e.agents[0])
        first = e.policy.shock(a, api, "X", "panic")
        rng_state = (e.rng.s, e.rng.spare)
        self.assertEqual(e.policy.shock(a, api, "X", "panic"), first)
        self.assertEqual((e.rng.s, e.rng.spare), rng_state)
        e.t = 15
        self.assertNotEqual(e.policy.shock(a, api, "X", "panic"), first)

    def test_body_collision_rejects_overlap(self):
        # Disable region checks to isolate body exclusion from wall geometry.
        e = make_engine(2)
        e.config.limits.enforceRegions = False
        a, b = e.agents
        relocate(e, a, floor=0, x=0, y=35)
        relocate(e, b, floor=0, x=2, y=35)
        self.assertFalse(e._clear(a, b.x, b.y))
        self.assertGreater(e.metrics.collisionRejections, 0)
        self.assertTrue(e._clear(a, -2, 35))

    def test_row_projection_and_displacement_cap(self):
        # Even an extreme requested velocity must respect the row track and the
        # engine's displacement cap; nonfinite requests must fail explicitly.
        e = make_engine(1)
        e.config.limits.hardCollisions = False
        a = e.agents[0]
        e._move(a, Record(vx=100, vy=-100))
        self.assertAlmostEqual(G.radius(a, e.g), a.seat.r, places=10)
        relocate(e, a, region="foyer", floor=0, x=0, y=35)
        e._move(a, Record(vx=100, vy=0))
        self.assertAlmostEqual(a.x, .7)
        with self.assertRaises(ValueError):
            e._move(a, Record(vx=math.nan, vy=0))

    def test_portal_tokens_disable_and_landing(self):
        # Exercise three independent service conditions: enabled state, capacity,
        # and a checked destination landing after successful admission.
        e = make_engine(1)
        a, p = e.agents[0], e.portal_map["AUD4"]
        relocate(e, a, floor=0, region="rim", x=p.x, y=p.y)
        p.enabled = False
        self.assertFalse(e.use_portal(a, p.id))
        p.enabled, p.tokens = True, 0
        self.assertFalse(e.use_portal(a, p.id))
        p.tokens = 1
        self.assertTrue(e.use_portal(a, p.id))
        self.assertEqual(a.region, "corridor")
        self.assertEqual(p.passed, 1)
        self.assertEqual(p.tokens, 0)
        self.assertTrue(G.inside_region(a, a.x, a.y, e.g))

    def test_stair_transfer_to_foyer_and_outside(self):
        # Stairs remove the planar body, wait on a timer, and use different
        # completion behavior for back/foyer versus stage/outside destinations.
        for portal_id in ("BACK_E", "STAGE_E"):
            e = make_engine(1)
            a, p = e.agents[0], e.portal_map[portal_id]
            relocate(e, a, floor=1, region="balcony-rim", x=p.x, y=p.y)
            p.tokens = 1
            self.assertTrue(e.use_portal(a, portal_id))
            self.assertEqual((a.floor, a.region), (-1, "stairs"))
            self.assertGreater(a.stairUntil, e.t)
            a.stairUntil = e.t
            e.step()
            if portal_id == "BACK_E":
                self.assertEqual((a.floor, a.region), (0, "foyer"))
            else:
                self.assertTrue(a.exited)
                self.assertEqual(a.exitId, portal_id)

    def test_closed_door_is_discovered_only_when_near(self):
        # The agent's knowledge must not silently track the engine's global switch.
        e = make_engine(1)
        a, p = e.agents[0], e.portal_map["AUD4"]
        a.data.portal = p.id
        p.enabled = False
        e.policy.observe_closures(a, e.context(a))
        self.assertNotIn(p.id, a.data.knownBlocked)
        relocate(e, a, floor=0, region="rim", x=p.x, y=p.y)
        e.policy.observe_closures(a, e.context(a))
        self.assertIn(p.id, a.data.knownBlocked)
        self.assertNotEqual(a.data.portal, p.id)

    def test_custom_policy_callbacks_and_order(self):
        # Minimal callbacks verify the engine does not require the bundled utility
        # model and visits every participant once in a randomized tick order.
        class Policy:
            def __init__(self): self.setup_ids, self.tick_ids = [], []
            def setup(self, a, api): self.setup_ids.append(a.id)
            def before_tick(self, api): self.tick_ids = []
            def decide(self, a, api): self.tick_ids.append(a.id); return dict(vx=0, vy=0)
        policy = Policy()
        e = make_engine(10, policy=policy)
        self.assertEqual(policy.setup_ids, list(range(10)))
        e.step()
        self.assertEqual(sorted(policy.tick_ids), list(range(10)))
        self.assertNotEqual(policy.tick_ids, list(range(10)))

    def test_source_editor_compiles_python_and_rejects_bad_policy(self):
        # The editor supports a full Python module, including dataclasses. A module
        # without a callable decide() is rejected before an experiment is started.
        p = compile_policy(default_policy_source())
        self.assertTrue(callable(p.decide))
        custom = "def create_policy(settings=None):\n    return {'decide': lambda a, api: {'vx': 0, 'vy': 0}}\n"
        e = make_engine(2, policy=compile_policy(custom))
        e.run_steps(3)
        self.assertEqual(e.tick, 3)
        dataclass_policy = ("from __future__ import annotations\nfrom dataclasses import dataclass\n"
                            "@dataclass\nclass UserModel:\n    speed: float = 0\n"
                            "    def decide(self, a, api): return {'vx': self.speed, 'vy': 0}\n"
                            "def create_policy(settings=None): return UserModel()\n")
        self.assertTrue(callable(compile_policy(dataclass_policy).decide))
        with self.assertRaises(ValueError):
            compile_policy("def create_policy(settings=None): return {}")

    def test_export_and_csv(self):
        # Saved snapshots must be detached, while source-compatible and expanded
        # CSV formats must remain distinguishable by their headers.
        e = make_engine(2)
        payload = e.export()
        json.dumps(payload, allow_nan=False)
        payload["agents"][0]["data"]["weights"]["T"] = -123
        self.assertGreater(e.agents[0].data.weights.T, 0)
        self.assertEqual(len(e.agents_csv().splitlines()), 3)
        self.assertNotIn("wT", e.agents_csv().splitlines()[0])
        self.assertIn("wT", e.agents_csv(True).splitlines()[0])

    def test_time_limit_and_retention(self):
        # A stopped run can remain incomplete; bounded logs/history prevent
        # unbounded memory growth without claiming to be complete trajectories.
        e = make_engine(2)
        e.config.limits.maxSeconds = .3
        e.run()
        self.assertEqual(e.summary()["status"], "time_limit")
        self.assertIsNone(e.summary()["clearanceTime"])
        tick = e.tick
        e.step()
        self.assertEqual(e.tick, tick)
        for _ in range(2200):
            e._push_history()
            e.log("test")
        self.assertEqual(len(e.history), 2000)
        self.assertEqual(len(e.events), 150)

    def test_cli_exports_and_output_boundaries(self):
        # Temporary output files stay within this port and are cleaned up by the
        # test context. Validate actual serialized contents, not just file existence.
        with tempfile.TemporaryDirectory(dir=ROOT / "results") as directory:
            relative = Path(directory).relative_to(ROOT)
            args = ["--n", "5", "--ticks", "5", "--disable-portal", "AUD4",
                    "--output", str(relative / "run.json"), "--csv", str(relative / "agents.csv"), "--include-weights"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 2)
            payload = json.loads((Path(directory) / "run.json").read_text())
            self.assertEqual(payload["summary"]["ticks"], 5)
            self.assertFalse(next(p for p in payload["portals"] if p["id"] == "AUD4")["enabled"])
            self.assertIn("wT", (Path(directory) / "agents.csv").read_text().splitlines()[0])
        with self.assertRaises(ValueError):
            output_path("../outside.json")
        with self.assertRaises(ValueError):
            output_path("run.py")

    def test_user_input_validation(self):
        # Reject impossible populations and unsupported public timestep/seed inputs.
        for changes in (dict(population=0), dict(population=1330), dict(dt=0), dict(dt=.5), dict(seed=-1)):
            config = default_config()
            config.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_config(config)

    def test_viewer_is_read_only_and_caches_static_geometry(self):
        # A fake canvas exercises actual drawing calls without requiring a desktop.
        # The full engine snapshot must remain unchanged after rendering both floors.
        class Canvas:
            def __init__(self): self.calls = []
            def winfo_width(self): return 600
            def winfo_height(self): return 600
            def __getattr__(self, name):
                return lambda *args, **kwargs: self.calls.append((name, args, kwargs))
        e, canvas = make_engine(), Canvas()
        before = copy.deepcopy(e.export())
        draw(canvas, e, 0)
        first = len(canvas.calls)
        draw(canvas, e, 0)
        self.assertLess(len(canvas.calls) - first, first)
        draw(canvas, e, 1)
        self.assertEqual(e.export(), before)


if __name__ == "__main__":
    unittest.main()
