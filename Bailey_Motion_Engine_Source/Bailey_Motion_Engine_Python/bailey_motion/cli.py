"""Headless runner and optional desktop interface for THIS Bailey model."""
import argparse
import json
from pathlib import Path

from .config import default_config, validate_config
from .engine import BaileyEngine
from .loader import compile_policy, default_policy_source
from .records import record

PORT_ROOT = Path(__file__).resolve().parent.parent
# Output locations are relative to this port; input filenames remain relative
# to the shell's working directory, allowing reusable world/policy files.


def output_path(value):
    # Resolve '..' and existing symlinks before enforcing the output boundary.
    # Validate before running, then use exclusive file creation when saving.
    path = (PORT_ROOT / value).resolve()
    if path == PORT_ROOT or not path.is_relative_to(PORT_ROOT):
        raise ValueError("Outputs must remain inside Bailey_Motion_Engine_Python.")
    if path.exists():
        raise ValueError(f"Output already exists: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"Output directory does not exist: {path.parent}")
    return path


def main(argv=None):
    # Passing argv directly supports tests; None reads the actual command line.
    parser = argparse.ArgumentParser(description="Python port of the current Bailey Motion Engine.")
    parser.add_argument("--population", "--n", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dt", type=float)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--ticks", type=int, help="Stop after this many ticks even if the world time limit is later.")
    parser.add_argument("--config", type=Path, help="World JSON; same format as the Bailey browser editor.")
    parser.add_argument("--settings", type=Path, help="Optional JSON overrides for bundled policy settings.")
    parser.add_argument("--policy", type=Path, help="Trusted editable Python policy source.")
    parser.add_argument("--disable-portal", action="append", default=[], metavar="ID")
    manager_mode = parser.add_mutually_exclusive_group()
    manager_mode.add_argument("--crowd-managers", action="store_true", help="Opt in to six stationary crowd managers.")
    manager_mode.add_argument("--no-crowd-managers", action="store_true", help="Disable staff even in a guided world.")
    parser.add_argument("--manager-settings", type=Path, help="Optional crowd-manager settings JSON, separate from policy settings.")
    student_mode = parser.add_mutually_exclusive_group()
    student_mode.add_argument("--students", action="store_true", help="All guests know the layout and choose shortest-distance routes.")
    student_mode.add_argument("--no-students", action="store_true", help="Use behavioral route choice even in a student-mode world.")
    led_mode = parser.add_mutually_exclusive_group()
    led_mode.add_argument("--led-strips", action="store_true", help="Enable constant-strength LED route guidance.")
    led_mode.add_argument("--no-led-strips", action="store_true", help="Disable LED guidance in a loaded world.")
    parser.add_argument("--led-strength", type=float, help="LED utility bonus; requires LED mode to be enabled.")
    parser.add_argument("--led-settings", type=Path, help="Optional LED settings JSON.")
    parser.add_argument("--no-collisions", action="store_true")
    parser.add_argument("--no-regions", action="store_true")
    parser.add_argument("--no-door-capacity", action="store_true")
    parser.add_argument("--output", help="Full-run JSON, relative to the Python port directory.")
    parser.add_argument("--csv", help="Agent CSV, relative to the Python port directory.")
    parser.add_argument("--include-weights", action="store_true", help="Append the four policy weights (T, P, N, S) to CSV.")
    parser.add_argument("--gui", "--animate", action="store_true", help="Open the Python desktop editor/viewer.")
    args = parser.parse_args(argv)
    try:
        if args.ticks is not None and args.ticks < 0:
            raise ValueError("ticks must be nonnegative.")
        config = (record(json.loads(args.config.read_text(encoding="utf-8"))) if args.config else default_config())
        # Precedence is defaults OR a supplied world, followed by explicit CLI
        # overrides. The world does not rescale to accommodate a larger population.
        for key in ("population", "seed", "dt"):
            value = getattr(args, key)
            if value is not None:
                config[key] = value
        if args.max_seconds is not None:
            config.limits.maxSeconds = args.max_seconds
        if args.students or args.no_students:
            config.studentMode = bool(args.students)
        if args.led_settings:
            config.ledStrips = record(json.loads(args.led_settings.read_text(encoding="utf-8")))
        if args.led_strips or args.no_led_strips:
            config.setdefault("ledStrips", record({}))["enabled"] = bool(args.led_strips)
        if args.led_strength is not None:
            config.setdefault("ledStrips", record({}))["strength"] = args.led_strength
        if args.manager_settings:
            config.crowdManagers = record(json.loads(args.manager_settings.read_text(encoding="utf-8")))
        if args.crowd_managers or args.no_crowd_managers:
            config.setdefault("crowdManagers", record({}))["enabled"] = args.crowd_managers
        if "crowdManagers" in config:
            from .crowd_managers import options
            options(config)
        for flag, setting in ((args.no_collisions, "hardCollisions"), (args.no_regions, "enforceRegions"),
                              (args.no_door_capacity, "doorCapacity")):
            if flag:
                config.limits[setting] = False
        validate_config(config)
        paths = [output_path(v) if v else None for v in (args.output, args.csv)]
        # JSON and CSV cannot target the same file or overwrite an existing run.
        if paths[0] is not None and paths[0] == paths[1]:
            raise ValueError("JSON and CSV output paths must differ.")
        source = args.policy.read_text(encoding="utf-8") if args.policy else default_policy_source()
        # A policy is executable Python. Optional settings are constructor overrides.
        settings = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings else None
        policy = compile_policy(source, settings, str(args.policy or "<bundled-policy>"))
        engine = BaileyEngine(config, policy)
        for portal_id in args.disable_portal:
            # Disable after setup, matching a live browser toggle. Agents still
            # have to discover closures through their policy's observation rule.
            if portal_id not in engine.portal_map:
                raise ValueError(f"Unknown portal: {portal_id}")
            engine.portal_map[portal_id].enabled = False
        if args.gui:
            # The GUI can reset or replace its engine/source, so retain what it
            # returns rather than exporting the initial object after closing.
            from .app import run_gui
            engine, source = run_gui(engine, source)
        elif args.ticks is not None:
            # Bounded observation runs may stop before either clearance or time limit.
            engine.run_steps(args.ticks)
        else:
            # Full headless runs continue through the world's own stopping condition.
            engine.run()
        summary = engine.summary()
        if engine.crowd is not None:
            summary["crowdManagers"] = engine.crowd.summary()
        if not engine.finished:
            summary["stopReason"] = "window_closed" if args.gui else "tick_limit"
        print(json.dumps(summary, indent=2, allow_nan=False))
        if paths[0]:
            # Full JSON includes current custom policy state, settings, and source.
            payload = engine.export()
            payload["policySource"] = source
            payload["summary"] = summary
            with paths[0].open("x", encoding="utf-8") as output:
                json.dump(payload, output, indent=2, allow_nan=False)
        if paths[1]:
            # Source-format CSV is preserved unless --include-weights is requested.
            with paths[1].open("x", encoding="utf-8", newline="") as output:
                output.write(engine.agents_csv(args.include_weights))
        # Exit 2 indicates an incomplete experiment, not a configuration failure.
        return 0 if engine.done == len(engine.agents) else 2
    except (ValueError, OSError, ImportError, RuntimeError, KeyError, TypeError, SyntaxError, AttributeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
