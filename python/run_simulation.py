"""Run the Python model; use --animate for an optional Tk desktop display."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from auditorium import Simulation, SimulationConfig, WEIGHT_NAMES, recommended_size

# This is the python/ engine directory, regardless of the shell's current folder.
# Config input paths use the shell's folder; output paths use this fixed base.
PROJECT_ROOT = Path(__file__).resolve().parent


def project_output(value: str) -> Path:
    # Resolve '..' and existing symlinks before enforcing the output boundary.
    path = (PROJECT_ROOT / value).resolve()
    if path == PROJECT_ROOT or not path.is_relative_to(PROJECT_ROOT):
        raise ValueError("Output files must stay inside the project directory.")
    if path.exists():
        # Preserving prior experiments also prevents accidental source-file overwrites.
        raise ValueError(f"Output already exists: {path}. Choose another filename.")
    if not path.parent.is_dir():
        raise ValueError(f"Output directory does not exist: {path.parent}")
    return path


def write_agents_csv(sim: Simulation, path: Path) -> None:
    # One row per person, including those still inside an incomplete experiment.
    # Blank exit fields distinguish unobserved exits from a zero-step exit time.
    columns = ["id", "initial_x", "initial_y", *[f"weight_{k}" for k in WEIGHT_NAMES],
               "beta_distance", "beta_congestion", "panic_susceptibility", "exited",
               "exit_name", "exit_time", "wait_steps", "moves", "switches"]
    # Exclusive creation enforces no-overwrite even if the file appeared after
    # validation; newline='' lets csv handle Windows line endings correctly.
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(columns)
        for a in sim.agents:
            exit_name = sim.building.exits[a.exit_id]["name"] if a.exit_id is not None else ""
            writer.writerow([a.id, *sim.building.position(a.initial_cell),
                             *[a.weights[k] for k in WEIGHT_NAMES], a.beta_distance,
                             a.beta_congestion, a.panic_susceptibility, a.exited, exit_name,
                             a.exit_time, a.wait_steps, a.moves, a.switches])


def make_parser() -> argparse.ArgumentParser:
    # Optional overrides default to None so omitted flags preserve JSON settings.
    parser = argparse.ArgumentParser(description="Agent-based exit simulation: square room, four doors.")
    parser.add_argument("--participants", "--n", type=int, help="Number of people (default: 150).")
    parser.add_argument("--size", type=int, help="Square side in cells; otherwise size for <=30%% initial occupancy.")
    parser.add_argument("--exit-width", type=int, help="Door width in cells.")
    parser.add_argument("--seed", type=int, help="Random seed (default: 42).")
    parser.add_argument("--max-steps", type=int, help="Termination limit (default: 5000).")
    parser.add_argument("--config", type=Path, help="JSON config; camelCase or snake_case keys.")
    parser.add_argument("--output", help="Optional full-run JSON path relative to the python directory.")
    parser.add_argument("--csv", help="Optional agent CSV path relative to the python directory.")
    parser.add_argument("--animate", action="store_true", help="Show an animated Tk window (requires tkinter).")
    parser.add_argument("--steps-per-frame", type=int, default=3, help="Initial animation speed (default: 3).")
    return parser


def main(argv: list[str] | None = None) -> int:
    # argv can be supplied directly by tests; None reads the real command line.
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        options = {}
        if args.config:
            # JSON supplies assumptions for an experiment, not fitted observations.
            with args.config.open(encoding="utf-8") as source:
                options = json.load(source)
        # Precedence: built-in defaults < configuration file < explicit CLI flags.
        config = SimulationConfig.from_dict(options)
        for name in ("participants", "seed", "max_steps"):
            value = getattr(args, name)
            if value is not None:
                setattr(config, name, value)
        if args.size is not None:
            config.geometry.size = args.size
        elif "size" not in options.get("geometry", {}):
            # Explicit exit coordinates depend on their original coordinate system.
            if config.geometry.exits is None:
                # Automatic sizing changes the building along with population size.
                # Pass --size explicitly for a comparison holding geometry fixed.
                config.geometry.size = recommended_size(config.participants)
        if args.exit_width is not None:
            config.geometry.exit_width = args.exit_width
        if args.steps_per_frame < 1:
            raise ValueError("steps-per-frame must be positive.")
        # Check output names before spending time running the experiment.
        # No file is created unless its corresponding output flag is supplied.
        output_path = project_output(args.output) if args.output else None
        csv_path = project_output(args.csv) if args.csv else None
        if output_path is not None and csv_path == output_path:
            raise ValueError("JSON and CSV must use different output files.")
        sim = Simulation(config)
        if args.animate:
            # Import graphics only when requested, keeping headless use independent
            # of Tcl/Tk. Closing the window returns the current, possibly partial run.
            from visualize import animate
            animate(sim, args.steps_per_frame)
        else:
            # Blocking headless mode stops at clearance or the configured step limit.
            sim.run()
        # JSON null marks unavailable statistics; NaN/Infinity are rejected so saved
        # results remain standard JSON and can be read by other analysis tools.
        print(json.dumps(sim.summary(), indent=2, allow_nan=False))
        if output_path:
            with output_path.open("x", encoding="utf-8") as output:
                json.dump(sim.export(), output, indent=2, allow_nan=False)
            print(f"Full results: {output_path}")
        if csv_path:
            write_agents_csv(sim, csv_path)
            print(f"Participants: {csv_path}")
        # Distinguish successful clearance from a limit or manually closed animation.
        return 0 if sim.complete else 2
    except (ValueError, TypeError, OSError, ImportError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    # Importing this module exposes helpers without launching an experiment.
    raise SystemExit(main())
