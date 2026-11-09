/* Optional command line interface: Node.js required; no packages to install. */
'use strict';
const fs = require('fs');
const path = require('path');
const { Simulation } = require('./model.js');

function main() {
  const args = process.argv.slice(2), flags = {};
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (key === '--help') {
      console.log('node javascript/cli.js [--participants 150] [--size 31] [--seed 42] [--max-steps 5000] [--config shared/building-example.json] [--out results/run.json]');
      console.log('Without an explicit size, a square is sized for <= 30% initial occupancy (minimum side 31). Output paths must be inside this project.');
      return;
    }
    if (!['--participants', '--size', '--seed', '--max-steps', '--config', '--out'].includes(key)) throw new Error(`Unknown option: ${key}`);
    if (i + 1 >= args.length || args[i + 1].startsWith('--')) throw new Error(`Missing value for ${key}`);
    flags[key] = args[++i];
  }
  const options = flags['--config'] ? JSON.parse(fs.readFileSync(flags['--config'], 'utf8')) : {};
  if (flags['--participants'] !== undefined) options.participants = Number(flags['--participants']);
  if (flags['--seed'] !== undefined) options.seed = Number(flags['--seed']);
  if (flags['--max-steps'] !== undefined) options.maxSteps = Number(flags['--max-steps']);
  options.geometry = { ...options.geometry };
  if (flags['--size'] !== undefined) options.geometry.size = Number(flags['--size']);
  else if (options.geometry.size === undefined) {
    let side = Math.max(31, Math.ceil(Math.sqrt((options.participants ?? 150) / 0.3)) + 2);
    if (side % 2 === 0) side++;
    options.geometry.size = side;
  }
  const output = path.resolve(__dirname, flags['--out'] || 'run.json');
  const relative = path.relative(__dirname, output);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Output must be a file inside the project directory.');
  // Use exclusive creation to avoid overwriting source or earlier experiment data.
  const sim = new Simulation(options); sim.run();
  fs.writeFileSync(output, JSON.stringify(sim.export(), null, 2), { flag: 'wx' });
  console.log(JSON.stringify(sim.summary(), null, 2));
  console.log(`Full results written to ${output}`);
  if (!sim.complete) process.exitCode = 2;
}
try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
