/* Dependency-free agent-based exit model. Coordinates and time are abstract units. */
(function (root) {
  'use strict';

  const WEIGHT_NAMES = ['time', 'habit', 'peer', 'norm', 'switching'];
  const DEFAULTS = {
    participants: 150, seed: 42, maxSteps: 5000,
    weightMean: 0.5, weightVariance: 1,
    observationRadius: 5, reconsiderAfter: 10, reconsiderEvery: 8,
    explorationProbability: 0.02, conflictFriction: 0.05,
    timeReference: 10, panicTimeScale: 100, residualStd: 0.2,
    distanceScale: 1, congestionScale: 1, panicScale: 1,
    geometry: { type: 'square', size: 31, exitWidth: 1, obstacles: [] }
  };

  class Random {
    constructor(seed) { this.state = (seed >>> 0) || 0x9e3779b9; }
    uniform() {
      let x = this.state;
      x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
      this.state = x >>> 0;
      return (this.state + 0.5) / 4294967296;
    }
    normal(mean = 0, variance = 1) {
      return mean + Math.sqrt(variance) * Math.sqrt(-2 * Math.log(this.uniform())) *
        Math.cos(2 * Math.PI * this.uniform());
    }
    pick(items) { return items[Math.floor(this.uniform() * items.length)]; }
    shuffle(items) {
      for (let i = items.length - 1; i > 0; i--) {
        const j = Math.floor(this.uniform() * (i + 1));
        [items[i], items[j]] = [items[j], items[i]];
      }
      return items;
    }
  }

  function check(condition, message) { if (!condition) throw new Error(message); }
  function integer(value, minimum, label) {
    check(Number.isInteger(value) && value >= minimum, `${label} must be an integer >= ${minimum}.`);
  }

  // GEOMETRY EXTENSION POINT: replace the square builder or supply explicit exit cells.
  // Obstacles are rectangles {x, y, width, height}; coordinates are zero-based.
  class Building {
    constructor(config) {
      check(config.type === 'square', 'Supported geometry type is currently square.');
      integer(config.size, 7, 'Room size');
      this.size = config.size;
      this.cellCount = this.size * this.size;
      this.walkable = new Uint8Array(this.cellCount);
      this.exitAt = new Int32Array(this.cellCount).fill(-1);
      for (let y = 1; y < this.size - 1; y++) {
        for (let x = 1; x < this.size - 1; x++) this.walkable[this.index(x, y)] = 1;
      }
      for (const rect of config.obstacles || []) {
        for (const key of ['x', 'y']) integer(rect[key], 1, `Obstacle ${key}`);
        for (const key of ['width', 'height']) integer(rect[key], 1, `Obstacle ${key}`);
        check(rect.x + rect.width <= this.size - 1 && rect.y + rect.height <= this.size - 1,
          'Obstacle must lie inside the boundary walls.');
        for (let y = rect.y; y < rect.y + rect.height; y++) {
          for (let x = rect.x; x < rect.x + rect.width; x++) this.walkable[this.index(x, y)] = 0;
        }
      }
      if (config.exits) {
        check(Array.isArray(config.exits) && config.exits.length > 0, 'Provide at least one exit.');
        this.exits = config.exits.map(e => ({ name: e.name, cells: e.cells.map(c => ({ ...c })) }));
      } else {
        const width = config.exitWidth;
        integer(width, 1, 'Exit width');
        check(width <= this.size - 2, 'Exit width exceeds the usable wall length.');
        const start = Math.floor((this.size - width) / 2);
        const axis = Array.from({ length: width }, (_, i) => start + i);
        this.exits = [
          { name: 'North', cells: axis.map(x => ({ x, y: 0 })) },
          { name: 'East', cells: axis.map(y => ({ x: this.size - 1, y })) },
          { name: 'South', cells: axis.map(x => ({ x, y: this.size - 1 })) },
          { name: 'West', cells: axis.map(y => ({ x: 0, y })) }
        ];
      }
      const names = new Set();
      this.exits.forEach((exit, k) => {
        check(typeof exit.name === 'string' && exit.name.length > 0 && !names.has(exit.name),
          'Exit names must be nonempty and unique.');
        names.add(exit.name);
        check(exit.cells.length > 0, 'Every exit needs at least one cell.');
        for (const { x, y } of exit.cells) {
          integer(x, 0, 'Exit x'); integer(y, 0, 'Exit y');
          check(x < this.size && y < this.size &&
            ((x === 0 || x === this.size - 1) !== (y === 0 || y === this.size - 1)),
            'Exit cells must be on a boundary wall, excluding corners.');
          const cell = this.index(x, y);
          check(this.exitAt[cell] === -1, 'Exit cells cannot overlap.');
          this.exitAt[cell] = k;
          this.walkable[cell] = 1;
        }
      });
      this.neighbors = Array.from({ length: this.cellCount }, (_, cell) => {
        const { x, y } = this.position(cell);
        return [[x, y - 1], [x + 1, y], [x, y + 1], [x - 1, y]]
          .filter(([a, b]) => a >= 0 && b >= 0 && a < this.size && b < this.size)
          .map(([a, b]) => this.index(a, b)).filter(c => this.walkable[c]);
      });
      // Navigation fields belong to the simulator, not the utility's distance estimate.
      this.fields = this.exits.map((exit, k) => this.distanceField(exit, k));
      this.spawnCells = [];
      for (let cell = 0; cell < this.cellCount; cell++) {
        if (this.walkable[cell] && this.exitAt[cell] === -1) {
          check(this.fields.some(f => f[cell] >= 0), 'An interior region has no reachable exit.');
          this.spawnCells.push(cell);
        }
      }
    }
    index(x, y) { return y * this.size + x; }
    position(cell) { return { x: cell % this.size, y: Math.floor(cell / this.size) }; }
    distanceField(exit, exitId) {
      const field = new Int32Array(this.cellCount).fill(-1);
      const queue = exit.cells.map(({ x, y }) => this.index(x, y));
      queue.forEach(c => { field[c] = 0; });
      for (let head = 0; head < queue.length; head++) {
        const c = queue[head];
        for (const n of this.neighbors[c]) {
          if (field[n] < 0 && (this.exitAt[n] === -1 || this.exitAt[n] === exitId)) {
            field[n] = field[c] + 1; queue.push(n);
          }
        }
      }
      return field;
    }
    perceivedDistance(cell, exitId) {
      const p = this.position(cell);
      return Math.min(...this.exits[exitId].cells.map(e => Math.abs(p.x - e.x) + Math.abs(p.y - e.y)));
    }
  }

  class Simulation {
    constructor(options = {}) {
      this.config = { ...DEFAULTS, ...options, geometry: { ...DEFAULTS.geometry, ...options.geometry } };
      const c = this.config;
      integer(c.participants, 0, 'Participants'); integer(c.seed, 0, 'Seed');
      check(c.seed <= 4294967295, 'Seed must fit in an unsigned 32-bit integer.');
      integer(c.maxSteps, 1, 'Maximum steps');
      integer(c.observationRadius, 0, 'Observation radius');
      integer(c.reconsiderAfter, 1, 'Reconsideration threshold');
      integer(c.reconsiderEvery, 1, 'Reconsideration interval');
      for (const key of ['weightMean', 'weightVariance', 'residualStd', 'distanceScale', 'congestionScale', 'panicScale']) {
        check(Number.isFinite(c[key]) && (key === 'weightMean' || c[key] >= 0), `Invalid ${key}.`);
      }
      for (const key of ['timeReference', 'panicTimeScale']) check(Number.isFinite(c[key]) && c[key] > 0, `Invalid ${key}.`);
      for (const key of ['explorationProbability', 'conflictFriction']) {
        check(Number.isFinite(c[key]) && c[key] >= 0 && c[key] <= 1, `${key} must lie in [0, 1].`);
      }
      this.building = new Building(c.geometry);
      check(c.participants <= this.building.spawnCells.length,
        `Room has ${this.building.spawnCells.length} initial places; enlarge geometry.size for ${c.participants} participants.`);
      this.rng = new Random(c.seed);
      const cells = this.rng.shuffle(this.building.spawnCells.slice());
      this.agents = Array.from({ length: c.participants }, (_, id) => {
        const weights = Object.fromEntries(WEIGHT_NAMES.map(name =>
          [name, this.rng.normal(c.weightMean, c.weightVariance)]));
        const reachable = this.building.exits.map((_, k) => k).filter(k => this.building.fields[k][cells[id]] >= 0);
        return {
          id, initialCell: cells[id], cell: cells[id], weights,
          // These bounded auxiliary parameters are distinct from the five normal weights.
          betaDistance: this.rng.uniform(), betaCongestion: 2 * this.rng.uniform() - 1,
          panicSusceptibility: this.rng.uniform(),
          panicByExit: this.building.exits.map(() => this.rng.normal()),
          entranceExit: this.rng.pick(reachable), target: -1,
          exited: false, exitId: null, exitTime: null, waitSteps: 0,
          blockedSteps: 0, moves: 0, switches: 0, decisions: 0,
          lastDecision: -Infinity, lastEvaluation: null
        };
      });
      this.time = 0; this.conflicts = 0; this.frictionEvents = 0;
      this.exitCounts = this.building.exits.map(() => 0);
      this.history = [{ time: 0, exited: 0, active: c.participants, conflicts: 0 }];
      this.occupancy = this.makeOccupancy();
    }
    get exitedCount() { return this.exitCounts.reduce((a, b) => a + b, 0); }
    get complete() { return this.exitedCount === this.agents.length; }
    get finished() { return this.complete || this.time >= this.config.maxSteps; }
    makeOccupancy() {
      const occupancy = new Int32Array(this.building.cellCount).fill(-1);
      for (const a of this.agents) if (!a.exited) occupancy[a.cell] = a.id;
      return occupancy;
    }
    // OBSERVATION EXTENSION POINT: add line of sight, signage, memory, or hidden exits here.
    observe(agent, occupancy, targets) {
      const b = this.building, r = this.config.observationRadius, p = b.position(agent.cell);
      const counts = b.exits.map(() => 0), neighbors = [];
      for (let y = Math.max(1, p.y - r); y <= Math.min(b.size - 2, p.y + r); y++) {
        for (let x = Math.max(1, p.x - r); x <= Math.min(b.size - 2, p.x + r); x++) {
          if (Math.abs(x - p.x) + Math.abs(y - p.y) > r) continue;
          const id = occupancy[b.index(x, y)];
          if (id >= 0 && id !== agent.id) {
            neighbors.push(this.agents[id]);
            if (targets[id] >= 0) counts[targets[id]]++;
          }
        }
      }
      return { counts, neighbors, targets };
    }
    // UTILITY EXTENSION POINT: all decision features and image-based terms live here.
    evaluate(agent, observation, oldTarget) {
      const b = this.building, c = this.config, w = agent.weights;
      const available = b.exits.map((_, k) => k).filter(k => b.fields[k][agent.cell] >= 0);
      const distances = b.exits.map((_, k) => b.perceivedDistance(agent.cell, k));
      const dmin = Math.min(...available.map(k => distances[k]));
      const counts = available.map(k => observation.counts[k]);
      const nmin = Math.min(...counts), nmax = Math.max(...counts);
      const known = counts.reduce((a, v) => a + v, 0);
      return available.map(k => {
        const crowd = nmax === nmin ? 0 : (observation.counts[k] - nmin) / (nmax - nmin);
        const congestion = nmax === nmin ? 1 : agent.betaCongestion >= 0
          ? Math.pow(crowd, agent.betaCongestion)
          : Math.pow(1 - crowd, -agent.betaCongestion);
        const distance = Math.pow((dmin + 1) / (distances[k] + 1), agent.betaDistance);
        // Proxy for delay, not an oracle of global queues: visible commitments / door width.
        const time = (distances[k] + observation.counts[k] / b.exits[k].cells.length) / c.timeReference;
        const habit = Number(agent.entranceExit === k);
        const peer = known ? observation.counts[k] / known : 0;
        // Explicit proxy: pursuing a target while nearby, longer-waiting people are ahead.
        const waitingAhead = observation.neighbors.filter(other =>
          other.waitSteps > agent.waitSteps &&
          b.perceivedDistance(other.cell, k) < distances[k] && observation.targets[other.id] === k).length;
        const norm = observation.neighbors.length ? waitingAhead / observation.neighbors.length : 0;
        const switching = Number(oldTarget >= 0 && oldTarget !== k);
        const behavioral = -w.time * time + w.habit * habit + w.peer * peer - w.norm * norm - w.switching * switching;
        const panic = agent.panicSusceptibility * agent.panicByExit[k] *
          (1 - Math.exp(-this.time / c.panicTimeScale));
        const residual = this.rng.normal(0, c.residualStd ** 2);
        return { exit: k, utility: c.distanceScale * distance + c.congestionScale * congestion +
          behavioral + c.panicScale * panic + residual,
          features: { distance, congestion, time, habit, peer, norm, switching, behavioral, panic, residual } };
      });
    }
    step() {
      if (this.finished) return false;
      const c = this.config, b = this.building, occupancy = this.occupancy;
      const targets = this.agents.map(a => a.target);
      // Decisions all observe previous targets and pre-movement positions.
      for (const agent of this.agents) {
        if (agent.exited) continue;
        const reconsider = agent.target < 0 || (agent.blockedSteps >= c.reconsiderAfter &&
          this.time - agent.lastDecision >= c.reconsiderEvery);
        if (reconsider) {
          const evaluations = this.evaluate(agent, this.observe(agent, occupancy, targets), targets[agent.id]);
          const best = Math.max(...evaluations.map(e => e.utility));
          let chosen = this.rng.pick(evaluations.filter(e => Math.abs(e.utility - best) < 1e-12));
          if (this.rng.uniform() < c.explorationProbability) chosen = this.rng.pick(evaluations);
          if (agent.target >= 0 && agent.target !== chosen.exit) agent.switches++;
          agent.target = chosen.exit; agent.lastDecision = this.time; agent.decisions++;
          agent.lastEvaluation = evaluations;
        }
      }
      const requests = new Map();
      for (const a of this.agents) {
        if (a.exited) continue;
        const field = b.fields[a.target];
        const choices = b.neighbors[a.cell].filter(n => occupancy[n] < 0 && field[n] >= 0 &&
          field[n] < field[a.cell] && (b.exitAt[n] < 0 || b.exitAt[n] === a.target));
        if (!choices.length) continue;
        const minimum = Math.min(...choices.map(n => field[n]));
        const next = this.rng.pick(choices.filter(n => field[n] === minimum));
        if (!requests.has(next)) requests.set(next, []);
        requests.get(next).push(a.id);
      }
      const moves = [];
      let tickConflicts = 0;
      for (const [cell, contenders] of requests) {
        if (contenders.length > 1) {
          tickConflicts++;
          if (this.rng.uniform() < c.conflictFriction) { this.frictionEvents++; continue; }
        }
        moves.push([this.rng.pick(contenders), cell]);
      }
      const moved = new Set();
      for (const [id, cell] of moves) {
        const a = this.agents[id];
        a.cell = cell; a.moves++; a.blockedSteps = 0; moved.add(id);
        if (b.exitAt[cell] >= 0) {
          a.exited = true; a.exitId = b.exitAt[cell]; a.exitTime = this.time + 1;
          this.exitCounts[a.exitId]++;
        }
      }
      for (const a of this.agents) {
        if (!a.exited && !moved.has(a.id)) { a.waitSteps++; a.blockedSteps++; }
      }
      this.time++; this.conflicts += tickConflicts; this.occupancy = this.makeOccupancy();
      this.history.push({ time: this.time, exited: this.exitedCount,
        active: this.agents.length - this.exitedCount, conflicts: tickConflicts });
      return true;
    }
    run() { while (!this.finished) this.step(); return this.summary(); }
    summary() {
      const times = this.agents.filter(a => a.exited).map(a => a.exitTime).sort((a, b) => a - b);
      const mean = values => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
      return {
        status: this.complete ? 'complete' : this.finished ? 'step_limit' : 'running',
        participants: this.agents.length, exited: this.exitedCount,
        remaining: this.agents.length - this.exitedCount, elapsedSteps: this.time,
        clearanceTime: this.complete ? this.time : null,
        meanExitTimeAmongExited: mean(times),
        p95ExitTimeAmongExited: times.length ? times[Math.ceil(0.95 * times.length) - 1] : null,
        meanWaitingStepsAllParticipants: mean(this.agents.map(a => a.waitSteps)),
        switches: this.agents.reduce((s, a) => s + a.switches, 0),
        conflicts: this.conflicts, frictionEvents: this.frictionEvents,
        exitCounts: Object.fromEntries(this.building.exits.map((e, k) => [e.name, this.exitCounts[k]]))
      };
    }
    export() {
      return { version: 1, config: this.config, summary: this.summary(),
        history: this.history, agents: this.agents };
    }
  }
  root.AuditoriumModel = { Simulation, Building, Random, DEFAULTS, WEIGHT_NAMES };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.AuditoriumModel;
})(globalThis);
