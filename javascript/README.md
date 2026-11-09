# JavaScript engine

Open [index.html](index.html) in a browser. No installation, server, internet connection, or packages are needed. Set participant count, room size, exit width, and seed, then select Create / reset and Run. Click a participant to inspect its weights and state. Export full runs as JSON or individual results as CSV.

The default experiment has 150 people, a 31-cell square, and one centered exit per wall. The five behavioral weights are independent N(0.5, 1) draws with negative values retained. See [model definitions and geometry assumptions](../docs/model.md).

## Files

- `model.js`: standalone simulation engine.
- `app.js`, `index.html`, `style.css`: offline visual controls.
- `cli.js`: optional Node.js runner.
- `test-model.js`, `tests.html`: engine tests.
- `ui-tests.html`: browser control tests.
- `preview.png`: initial visual simulator screenshot.
- `results/`: saved example summaries and verification report.

## Geometry and command-line use

Expand Geometry & model configuration in the interface to edit geometry and model JSON. The shared example is [shared/building-example.json](../shared/building-example.json).

If Node.js is installed, run these commands from the **project root**:

```powershell
node javascript/cli.js --participants 150 --seed 42 --out results/new-run.json
node javascript/cli.js --participants 1000 --max-steps 20000 --out results/new-large-run.json
node javascript/cli.js --config shared/building-example.json --out results/new-obstacle-run.json
node javascript/test-model.js
```

`--config` is relative to your current working directory. `--out` is relative to **this javascript directory** and cannot escape it. Existing output files are never overwritten. Without an explicit geometry size, the CLI sizes a square for at most 30% initial occupancy. Exit codes: 0 for clearance, 2 for a step-limit run, 1 for errors.

## API and tests

In a browser, load `model.js`, then:

```js
const sim = new AuditoriumModel.Simulation({
  participants: 1000,
  seed: 42,
  maxSteps: 20000,
  geometry: { size: 61, exitWidth: 1, obstacles: [] }
});
console.log(sim.run());
const results = sim.export();
```

Use `sim.step()` for incremental updates and inspect `sim.agents`, `sim.occupancy`, and `sim.history`. Exports retain the configuration, summary, cumulative exits, individual parameters/states, and last utility evaluations, but not every historical position.

Open `tests.html` for engine tests. `ui-tests.html` uses a local iframe and may require a local server or a browser flag permitting local-file access. The simulator itself needs neither.

All 12 engine and 5 interface tests passed in Chrome. The Node CLI was syntax-checked; Node.js was unavailable in the development shell. Saved example summaries and the verification report are in `results/`.
