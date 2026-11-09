# Python engine

The Python implementation uses only the standard library and requires Python 3.10 or later. Run these commands from the **project root**, one directory above this file:

```powershell
python python/run_simulation.py --n 150
python python/run_simulation.py --n 150 --animate
python python/run_simulation.py --n 1000 --max-steps 20000
python python/run_simulation.py --config shared/building-example.json --output results/new-run.json --csv results/new-agents.csv
python -m unittest discover -s python -p "test_*.py" -v
```

This workspace includes a machine-specific local runtime for immediate headless execution:

```powershell
.\.python-runtime\python.exe python/run_simulation.py --n 150
.\.python-runtime\python.exe -m unittest discover -s python -p "test_*.py" -v
```

The local runtime stays at the project root and reads the installed Python standard library. It is ignored by Git and is not part of the portable source distribution. Tk's native file access could not initialize in this sandbox; use a regular Python installation with Tcl/Tk for animation.

## Files and configuration

- `auditorium.py`: typed configuration, agents, building geometry, observation, utility, movement, and exports.
- `run_simulation.py`: command-line runner and CSV/JSON exports.
- `visualize.py`: optional Tk animation with Run/Pause, single stepping, speed, and participant inspection.
- `test_auditorium.py`: 16 engine/CLI tests, including comparisons with JavaScript.
- `test_visualize.py`: optional hidden-window control test; skips if Tk cannot initialize.
- `python-reference.json`: JavaScript-generated cross-language test fixture.
- `results/`: saved JSON runs, participant CSV, and verification report.

Both engines use [shared/building-example.json](../shared/building-example.json). Python accepts snake_case and camelCase configuration keys. Unknown keys are rejected. The CLI sizes an unspecified square for at most 30% starting occupancy. Explicit geometry sizes take precedence.

`--config` is resolved relative to the current working directory. `--output` and `--csv` are resolved relative to **this python directory**, regardless of the current working directory. Use `results/new-run.json` to keep runs in `python/results/`. Existing files are never overwritten, and output paths cannot escape `python/`.

Headless runs print a summary and save files only when requested. Animation starts paused; click Run to begin. Closing the window returns the current run to the CLI for optional export. Exit codes: 0 for full clearance, 2 for incomplete runs, 1 for errors.

## Python API

From the `python/` directory, or with that directory on your Python import path:

```python
from auditorium import GeometryConfig, SimulationConfig, Simulation

config = SimulationConfig(
    participants=150,
    seed=42,
    max_steps=10_000,
    weight_mean=0.5,
    weight_variance=1.0,
    geometry=GeometryConfig(
        size=31,
        exit_width=1,
        obstacles=[],
    ),
)
sim = Simulation(config)
print(sim.run())
print(sim.agents[0].weights)
```

Use `sim.step()` for incremental updates, and `sim.export()` for a detached JSON-compatible snapshot. Before running to completion, you can animate an instance with `from visualize import animate; animate(sim)`.

Five behavioral weights are independent **N(0.5, 1)** draws; negative values are retained. Config and summary exports use camelCase for compatibility; Python agent fields use snake_case. The sampler and draw order match JavaScript, though platform floating-point differences can affect borderline decisions. See [model definitions and geometry assumptions](../docs/model.md).

## Verification

All 16 engine/CLI tests passed under Python 3.13.14. The Tk control test was skipped because native file access could not initialize in the sandbox. Recorded seed-42 runs cleared 150 participants in 933 steps and 1,000 participants in 5,655 steps, matching the JavaScript reference. Reports and saved runs are in `results/`.
