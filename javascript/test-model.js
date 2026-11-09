/* Run with Node: node test-model.js, or open tests.html in a browser. */
(function (root) {
  'use strict';
  function runModelTests(library) {
    const { Simulation, Building, Random, WEIGHT_NAMES } = library;
    const results = [];
    function assert(condition, message) { if (!condition) throw new Error(message); }
    function test(name, action) {
      try { action(); results.push({ name, passed: true }); }
      catch (error) { results.push({ name, passed: false, message: error.message }); }
    }
    function throws(action) { let thrown = false; try { action(); } catch (_) { thrown = true; } assert(thrown, 'Expected rejection.'); }
    function validate(sim) {
      const occupied = new Set();
      let exited = 0;
      for (const a of sim.agents) {
        assert(sim.building.walkable[a.cell], 'An agent entered a wall.');
        assert(a.moves + a.waitSteps === (a.exited ? a.exitTime : sim.time), 'Individual time accounting failed.');
        if (a.exited) {
          exited++;
          assert(sim.building.exitAt[a.cell] === a.exitId, 'Exited agent not at its recorded exit.');
        } else {
          assert(!occupied.has(a.cell), 'Agents overlap.'); occupied.add(a.cell);
          assert(sim.occupancy[a.cell] === a.id, 'Occupancy disagrees with agent state.');
          assert(sim.building.exitAt[a.cell] === -1, 'An agent remained on an exit.');
        }
      }
      assert(exited === sim.exitedCount, 'Exit count mismatch.');
      assert(occupied.size + exited === sim.config.participants, 'Population not conserved.');
    }
    test('Exact normal-weight sampling, negative values retained', () => {
      const sim = new Simulation({ participants: 800 });
      const values = sim.agents.flatMap(a => WEIGHT_NAMES.map(k => a.weights[k]));
      const mean = values.reduce((s, x) => s + x, 0) / values.length;
      const variance = values.reduce((s, x) => s + (x - mean) ** 2, 0) / values.length;
      assert(Math.abs(mean - 0.5) < 0.06, `Unexpected mean ${mean}`);
      assert(Math.abs(variance - 1) < 0.10, `Unexpected variance ${variance}`);
      assert(values.some(x => x < 0) && values.some(x => x > 1), 'Normal draws were clipped.');
    });
    test('Seeded simulations reproduce full outcomes', () => {
      const a = new Simulation({ participants: 40, seed: 33 }); a.run();
      const b = new Simulation({ participants: 40, seed: 33 }); b.run();
      assert(JSON.stringify(a.export()) === JSON.stringify(b.export()), 'Results differ for identical seeds.');
      const c = new Simulation({ participants: 40, seed: 34 });
      assert(a.agents[0].weights.time !== c.agents[0].weights.time, 'Seeds did not change draws.');
    });
    test('Zero participants finishes at time zero', () => {
      const sim = new Simulation({ participants: 0 });
      assert(sim.complete && !sim.step() && sim.run().clearanceTime === 0, 'Empty population failed.');
    });
    test('Default 150-person experiment clears with four exits', () => {
      const sim = new Simulation(); sim.run(); validate(sim);
      assert(sim.complete, 'Default run did not finish.');
      assert(sim.exitCounts.length === 4 && sim.exitCounts.every(n => n > 0), 'Expected four used exits.');
    });
    test('Simultaneous movement preserves exclusion, speed, and exit capacity', () => {
      const sim = new Simulation({ participants: 90, seed: 8, maxSteps: 800, geometry: { size: 15 } });
      while (!sim.finished) {
        const before = sim.agents.map(a => ({ cell: a.cell, exited: a.exited }));
        const beforeExitCounts = sim.exitCounts.slice();
        const beforeCells = new Set(before.filter(a => !a.exited).map(a => a.cell));
        sim.step(); validate(sim);
        sim.agents.forEach((a, id) => {
          if (before[id].exited || a.cell === before[id].cell) return;
          const p = sim.building.position(before[id].cell), q = sim.building.position(a.cell);
          assert(Math.abs(p.x - q.x) + Math.abs(p.y - q.y) === 1, 'Movement exceeded one cell.');
          assert(!beforeCells.has(a.cell), 'Moved into a cell occupied in the initial snapshot.');
        });
        sim.exitCounts.forEach((count, k) => assert(count - beforeExitCounts[k] <= sim.building.exits[k].cells.length,
          'Exit throughput exceeded its width.'));
      }
      assert(sim.conflicts > 0, 'Test did not exercise conflicts.');
    });
    test('Congestion, distance, and behavioral features follow utility definition', () => {
      const sim = new Simulation({ participants: 1, residualStd: 0 });
      const a = sim.agents[0]; a.cell = sim.building.index(15, 15);
      a.weights = { time: 1, habit: 0, peer: 0, norm: 0, switching: 0 };
      a.betaCongestion = 1;
      const observation = { counts: [0, 1, 2, 3], neighbors: [], targets: [-1] };
      const values = sim.evaluate(a, observation, -1);
      assert(values[0].features.congestion === 0 && values[3].features.congestion === 1, 'Positive congestion branch wrong.');
      a.betaCongestion = -1;
      const reversed = sim.evaluate(a, observation, -1);
      assert(reversed[0].features.congestion === 1 && reversed[3].features.congestion === 0, 'Negative congestion branch wrong.');
      for (const e of values) {
        assert(e.features.distance === 1, 'Equal distances should give distance score 1.');
        assert(Math.abs(e.utility - (1 + e.features.congestion - e.features.time)) < 1e-10, 'Utility sum incorrect.');
      }
    });
    test('Observations retain old target commitments during decision updates', () => {
      const sim = new Simulation({ participants: 2, residualStd: 0 });
      const [a, other] = sim.agents;
      a.cell = sim.building.index(15, 16); other.cell = sim.building.index(15, 15);
      other.waitSteps = 5; other.target = 0;
      const obs = sim.observe(a, sim.makeOccupancy(), [-1, 0]);
      other.target = 1;
      const values = sim.evaluate(a, obs, -1);
      assert(values.find(e => e.exit === 0).features.norm === 1, 'Norm feature read a new commitment.');
      assert(values.find(e => e.exit === 1).features.norm === 0, 'Norm feature leaked an updated target.');
    });
    test('Rectangular obstacles block cells and allow navigation around them', () => {
      const sim = new Simulation({ participants: 40, seed: 7,
        geometry: { size: 21, obstacles: [{ x: 9, y: 5, width: 3, height: 11 }] } });
      assert(!sim.building.walkable[sim.building.index(10, 10)], 'Obstacle not applied.');
      while (!sim.finished) { sim.step(); validate(sim); }
      assert(sim.complete, 'Obstacle run failed to clear.');
    });
    test('Custom exit placement and multi-cell exit widths work', () => {
      const sim = new Simulation({ participants: 15, geometry: { size: 11,
        exits: [{ name: 'Door', cells: [{ x: 4, y: 0 }, { x: 5, y: 0 }] }] } });
      sim.run(); validate(sim); assert(sim.complete && sim.exitCounts[0] === 15, 'Custom door failed.');
      const wide = new Building({ type: 'square', size: 11, exitWidth: 3 });
      assert(wide.exits.every(e => e.cells.length === 3), 'Exit width not applied.');
    });
    test('Max-step termination reports incomplete run honestly', () => {
      const sim = new Simulation({ participants: 150, maxSteps: 1 }); const s = sim.run();
      assert(s.status === 'step_limit' && s.clearanceTime === null && s.remaining > 0, 'Censored run misreported.');
      assert(!sim.step(), 'Stepped past limit.');
    });
    test('Input validation rejects invalid or impossible configurations', () => {
      throws(() => new Simulation({ participants: -1 }));
      throws(() => new Simulation({ participants: 26, geometry: { size: 7 } }));
      throws(() => new Simulation({ weightVariance: -1 }));
      throws(() => new Simulation({ geometry: { size: 7, exitWidth: 6 } }));
      throws(() => new Simulation({ geometry: { size: 9, exits: [{ name: 'Corner', cells: [{ x: 0, y: 0 }] }] } }));
      throws(() => new Simulation({ geometry: { size: 9, obstacles: [{ x: 2, y: 2, width: 99, height: 1 }] } }));
      // Isolate the center cell completely from every exit.
      throws(() => new Simulation({ geometry: { size: 9, obstacles: [
        { x: 3, y: 3, width: 3, height: 1 }, { x: 3, y: 5, width: 3, height: 1 },
        { x: 3, y: 4, width: 1, height: 1 }, { x: 5, y: 4, width: 1, height: 1 }
      ] } }));
    });
    test('Normal sampler supports zero variance exactly', () => {
      const rng = new Random(42);
      for (let i = 0; i < 100; i++) assert(rng.normal(0.5, 0) === 0.5, 'Zero variance sampler incorrect.');
    });
    return results;
  }
  root.runModelTests = runModelTests;
  if (typeof module !== 'undefined' && module.exports) {
    const results = runModelTests(require('./model.js'));
    for (const r of results) console.log(`${r.passed ? 'PASS' : 'FAIL'} ${r.name}${r.message ? ': ' + r.message : ''}`);
    process.exitCode = results.every(r => r.passed) ? 0 : 1;
  }
})(globalThis);
