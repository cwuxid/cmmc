/* Offline visualization; the simulation engine in model.js has no DOM dependency. */
(function () {
  'use strict';
  const { Simulation } = AuditoriumModel;
  const $ = id => document.getElementById(id);
  const colors = ['#79d9c3', '#f7b96b', '#a9a0ff', '#f28eaa', '#82c9f4', '#dae779'];
  const color = k => k < 0 ? '#91a5b6' : colors[k % colors.length];
  const room = $('room'), ctx = room.getContext('2d');
  let sim, running = false, selected = null, extra = {};

  function status(message, error = false) {
    $('status').textContent = message; $('status').className = error ? 'error' : '';
  }
  function create(options) {
    try {
      const next = new Simulation(options);
      running = false; selected = null; sim = next;
      $('participants').value = sim.config.participants;
      $('size').value = sim.config.geometry.size;
      $('exitWidth').value = sim.config.geometry.exitWidth;
      $('seed').value = sim.config.seed;
      $('configuration').value = JSON.stringify(sim.config, null, 2);
      extra = JSON.parse(JSON.stringify(sim.config));
      status('Ready. Select Run to start.'); draw();
    } catch (error) { status(error.message, true); }
  }
  function format(v) { return v === null ? '—' : Number.isInteger(v) ? String(v) : v.toFixed(2); }
  function draw() {
    if (!sim) return;
    const b = sim.building, cell = room.width / b.size;
    ctx.fillStyle = '#0b131b'; ctx.fillRect(0, 0, room.width, room.height);
    for (let i = 0; i < b.cellCount; i++) {
      if (!b.walkable[i]) continue;
      const { x, y } = b.position(i);
      ctx.fillStyle = b.exitAt[i] >= 0 ? color(b.exitAt[i]) : '#223340';
      ctx.fillRect(x * cell + .5, y * cell + .5, cell - 1, cell - 1);
    }
    for (const a of sim.agents) {
      if (a.exited) continue;
      const { x, y } = b.position(a.cell);
      ctx.beginPath(); ctx.arc((x + .5) * cell, (y + .5) * cell, cell * .32, 0, 2 * Math.PI);
      ctx.fillStyle = color(a.target); ctx.fill();
      if (a.id === selected) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke(); }
    }
    const s = sim.summary();
    $('time').textContent = s.elapsedSteps;
    $('exited').textContent = `${s.exited} / ${s.participants}`;
    $('waiting').textContent = format(s.meanWaitingStepsAllParticipants);
    $('conflicts').textContent = s.conflicts;
    $('toggle').textContent = running ? 'Pause' : 'Run';
    $('toggle').disabled = sim.finished; $('step').disabled = sim.finished;
    $('legend').replaceChildren(...b.exits.map((e, k) => {
      const span = document.createElement('span'), dot = document.createElement('i');
      dot.style.background = color(k); span.append(dot, `${e.name}: ${sim.exitCounts[k]}`); return span;
    }));
    if (selected !== null) {
      const a = sim.agents[selected];
      $('inspector').textContent = JSON.stringify({
        id: a.id, position: b.position(a.cell),
        target: a.target < 0 ? null : b.exits[a.target].name,
        status: a.exited ? 'exited' : a.blockedSteps ? 'waiting' : 'active',
        weights: a.weights, betaDistance: a.betaDistance,
        betaCongestion: a.betaCongestion, panicSusceptibility: a.panicSusceptibility,
        entranceExit: b.exits[a.entranceExit].name,
        waitingSteps: a.waitSteps, moves: a.moves, switches: a.switches, exitTime: a.exitTime,
        lastDecisionScores: a.lastEvaluation
      }, null, 2);
    } else $('inspector').textContent = 'No participant selected.';
    drawChart();
  }
  function drawChart() {
    const canvas = $('chart'), g = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
    g.clearRect(0, 0, w, h); g.strokeStyle = '#486073'; g.lineWidth = 1;
    const left = 45, right = w - 15, top = 12, bottom = h - 30;
    g.beginPath(); g.moveTo(left, top); g.lineTo(left, bottom); g.lineTo(right, bottom); g.stroke();
    g.fillStyle = '#b2c4d3'; g.font = '12px Segoe UI';
    g.fillText(sim.agents.length, 3, top + 8); g.fillText('0', 25, bottom + 3);
    g.fillText('0', left, h - 8); g.fillText(`${sim.time} steps`, Math.max(left + 40, right - 70), h - 8);
    g.strokeStyle = '#79d9c3'; g.lineWidth = 2; g.beginPath();
    for (let i = 0; i < sim.history.length; i++) {
      const p = sim.history[i];
      const x = left + p.time / Math.max(1, sim.time) * (right - left);
      const y = bottom - p.exited / Math.max(1, sim.agents.length) * (bottom - top);
      if (!i) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.stroke();
  }
  function afterStep() {
    if (sim.finished) {
      running = false;
      status(sim.complete ? `Complete: all ${sim.agents.length} participants exited in ${sim.time} steps.` :
        `Step limit reached: ${sim.agents.length - sim.exitedCount} participants remain. Export the run to inspect blockage.`);
    } else status(running ? 'Running.' : 'Paused.');
    draw();
  }
  function download(name, data, type) {
    const url = URL.createObjectURL(new Blob([data], { type }));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  $('reset').onclick = () => create({ ...extra,
    participants: Number($('participants').value), seed: Number($('seed').value),
    geometry: { ...extra.geometry, size: Number($('size').value), exitWidth: Number($('exitWidth').value) }
  });
  $('apply').onclick = () => {
    try { create(JSON.parse($('configuration').value)); } catch (e) { status(e.message, true); }
  };
  $('toggle').onclick = () => { if (!sim.finished) { running = !running; afterStep(); } };
  $('step').onclick = () => { running = false; sim.step(); afterStep(); };
  $('json').onclick = () => download(`exit-run-seed-${sim.config.seed}.json`, JSON.stringify(sim.export(), null, 2), 'application/json');
  $('configDownload').onclick = () => download('building-config.json', JSON.stringify(sim.config, null, 2), 'application/json');
  $('csv').onclick = () => {
    const columns = ['id', 'initialX', 'initialY', 'timeWeight', 'habitWeight', 'peerWeight', 'normWeight', 'switchingWeight',
      'betaDistance', 'betaCongestion', 'panicSusceptibility', 'exited', 'exitId', 'exitTime', 'waitSteps', 'moves', 'switches'];
    const rows = sim.agents.map(a => {
      const p = sim.building.position(a.initialCell);
      return [a.id, p.x, p.y, ...AuditoriumModel.WEIGHT_NAMES.map(k => a.weights[k]), a.betaDistance,
        a.betaCongestion, a.panicSusceptibility, a.exited, a.exitId, a.exitTime, a.waitSteps, a.moves, a.switches].join(',');
    });
    download('participants.csv', [columns.join(','), ...rows].join('\r\n'), 'text/csv');
  };
  room.onclick = event => {
    const rect = room.getBoundingClientRect(), b = sim.building;
    const x = Math.floor((event.clientX - rect.left) / rect.width * b.size);
    const y = Math.floor((event.clientY - rect.top) / rect.height * b.size);
    if (x < 0 || y < 0 || x >= b.size || y >= b.size) return;
    const id = sim.occupancy[b.index(x, y)]; selected = id < 0 ? null : id; draw();
  };
  function frame() {
    if (running) {
      for (let i = 0; i < Number($('speed').value) && !sim.finished; i++) sim.step();
      afterStep();
    }
    requestAnimationFrame(frame);
  }
  create({}); requestAnimationFrame(frame);
})();
