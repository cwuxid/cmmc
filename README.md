# Auditorium movement model

The detailed Bailey auditorium model has separate [original JavaScript](Bailey_Motion_Engine_Source/Bailey_Motion_Engine/README.md) and [Python model](Bailey_Motion_Engine_Source/Bailey_Motion_Engine_Python/README.md) folders. The Python default now implements the supplied two-plan/barrier/stair specification. The instructions below describe the earlier abstract square-room model.

The Python and JavaScript engines are in separate directories. Both implement the same behavioral utility and movement rules, with five independent N(0.5, 1) behavioral weights per participant.

```text
modeling/
  python/                 Python engine, CLI, animation, and tests
    results/              Saved Python runs and verification
  javascript/             JavaScript engine, browser UI, CLI, and tests
    results/              Saved JavaScript examples and verification
  shared/                 Building configuration used by both engines
  docs/                   Model definitions and original conversation
    images/               Reference equations and images
  .python-runtime/        Local machine-specific runtime (ignored by Git)
  .browser-check/         Existing browser test profile (ignored by Git)
```

- [Python instructions](python/README.md)
- [JavaScript instructions](javascript/README.md)
- [Model definitions and geometry](docs/model.md)
- [Shared building example](shared/building-example.json)
- [Original conversation](docs/auditorium-exit-transcript.md)

Run these commands from this project root:

```powershell
python python/run_simulation.py --n 150
python python/run_simulation.py --n 150 --animate
python -m unittest discover -s python -p "test_*.py" -v
```

The local headless runtime is also available:

```powershell
.\.python-runtime\python.exe python/run_simulation.py --n 150
```

For the browser version, open [javascript/index.html](javascript/index.html).

To use the shared building example and save a Python run:

```powershell
python python/run_simulation.py --config shared/building-example.json --output results/new-run.json --csv results/new-agents.csv
```

Output filenames are relative to the corresponding engine directory: Python writes inside `python/`; the JavaScript CLI writes inside `javascript/`. Existing saved runs have been preserved in each engine's `results/` directory. Configuration paths passed to a CLI are relative to your current working directory.
