# Bailey Motion Engine — editable source project

A **mechanics engine**, not a calibrated evacuation simulator. Every person's route and motion command comes from editable user policy code; the engine supplies ticks, bodies, geometry, collision queries, coordinates, and visualization.

## Open / edit

- Open `index.html` in a browser; no server, Python environment, or external package is required.
- Edit the full model directly in the on-page **Movement & pathfinding source** editor, then select **Apply code + reset**. The editor compiles your own JavaScript; only run code you trust.
- For permanent changes in your code editor, modify `src/user-model.js` and reload. **Download edited model.js** exports your in-browser code to a regular source file.
- To alter the world in-browser, expand **Editable world geometry & probability distributions (JSON)**. For permanent changes, edit `src/config.js`.
- All mechanics are readable and replaceable in `src/engine.js`, `src/geometry.js`, and `src/random.js`.
- Run, pause, advance by one tick, click an agent to inspect state, disable doors, and export agents as CSV.

## Project layout

| File | What is in it |
| --- | --- |
| `src/user-model.js` | Your movement, pathfinding, exit selection, social logic; replace these freely |
| `src/engine.js` | Fixed-time stepping, deterministic RNG, motion integration, collisions, region transitions, door and stair service, state |
| `src/geometry.js` | Seat inventory, radial aisle/row collision domains, portals, geometric helpers |
| `src/config.js` | Every starting geometry dimension, seating capacity, distribution, and runtime switch |
| `src/random.js` | Seeded distributions: normal, beta, lognormal |
| `src/viewer.js` | Canvas drawing only; does not change agent coordinates |
| `src/app.js` | Browser UI, code compilation, controls and file exports |
| `style.css`, `index.html` | Interface |

The bundled single-file `Bailey_Motion_Engine_Standalone.html` is also supplied. Source files are preferable if you plan extensive changes.

## Model contract

`decide(agent, api)` is the **only required callback**. It returns a requested velocity vector in **metres per second**, e.g. `{vx: 1.1, vy: 0.2}`. The engine applies that movement during a fixed `dt` and, if enabled, rejects movement through the current region's barriers or into another person's body. It does **not** choose a direction, speed, acceleration, target, exit, or next stage.

Optional callbacks, each run in deterministic order:

```js
({
  setup(agent, api) { agent.data.goal = null; },
  decide(agent, api) { return { vx: 0, vy: 0 }; },
  afterMove(agent, api) { /* transitions / rerouting */ },
  onPortal(agent, portal, api) { /* e.g. choose another waypoint */ },
  onStairsComplete(agent, portal, api) {},
  beforeTick(api) {},
  afterTick(api) {},
  onExit(agent, api) {}
})
```

Read `src/user-model.js` for a short, replaceable route and constant-speed example. **The starter policy is intentionally simplistic and is not a crowd-dynamics formula.** You can substitute your own utility optimization, social forces, steering, probabilistic exit routing, path search, or group coordination without editing engine internals.

### Agent state

- `agent.x`, `.y` — current planar coordinates (metres); `vx`,`vy` — velocity (m/s)
- `agent.id`, `.floor` (0 main, 1 balcony, -1 in stairs, -2 outside), `.region`
- `agent.seat` — starting seat record, including `.x`, `.y`, `.r`, `.angle`, `.row`, `.block`, `.section`, `.leftAisle`, `.rightAisle`
- `agent.params` — seeded sample of every configured parameter, e.g. `.speed`, `.sanity`, `.groupthink`, `.pack`, `.norms`, `.reaction`, `.radius`
- `agent.radius` — collision radius (metres)
- `agent.data` — unrestricted dictionary for **your** internal policy state
- `agent.exited`, `agent.exitAt`, `agent.exitId`, `agent.blockedTicks`

### Model `api`

```js
api.t; api.dt; api.tick;
api.agents; api.geometry; api.portals;
api.random(); api.normal(); api.sample({type:'normal',mean:1,sd:.2});
api.point(radius, angleRadians); api.polar(agent); api.radius(agent);
api.distance(a, b); api.neighbors(agent, 2.5);
api.clear(agent, x, y, region);
api.setRegion(agent, 'aisle', x, y, {aisleAngle: 1.2});
api.portal('AUD4'); api.usePortal(agent, 'AUD4');
api.exit(agent, 'SPECIAL_EXIT');
api.log('custom model event');
```

`api.usePortal` is a *mechanical* service request, not a routing decision. It checks that the agent is in the correct region, close to the portal, the portal is enabled, and (optionally) has throughput tokens. It then carries the agent through the threshold or into a timed staircase. The user policy determines **which portal and when**. It is possible to use `api.exit` for custom exits in your own geometry or mechanics code.

Regions are `row`, `aisle`, `rim`, `corridor`, `foyer`, `balcony-rim`, `stairs`, `done`. Geometry determines where movement is permitted for each. For `row`, the engine projects motion onto the circular seat-row track, so an agent cannot step through rows even if a user policy requests an invalid direction. The model must explicitly transfer from the row to an aisle with `setRegion`; the sample policy handles this at the end of the row. Seats are allocated uniquely and have exact section counts 527 / 486 / 316 at full occupancy.

## Examples of replacing user formulas

In `computeVelocity` you might use desired acceleration and persist your previous velocity:

```js
const tau = 0.5;               // user-chosen relaxation time
const desiredX = directionX * agent.params.speed;
const desiredY = directionY * agent.params.speed;
return {
  vx: agent.vx + ((desiredX-agent.vx)/tau)*api.dt,
  vy: agent.vy + ((desiredY-agent.vy)/tau)*api.dt
};
```

In `pickExit`, replace the example distance scores with your own perceived travel-time utility, imitative choice, grouping penalties, congestion estimates, etc. No other part of the engine needs to know how those scores are calculated.

## Determinism and limitations

Reusing the same seed, source code, config, and sequence of user interactions results in repeatable tick evolution. Don't use `Math.random()` inside user policy; use `api.random()` so it is seeded. Avoid `Date.now()` for model time; use `api.t`.

This is an **editable engineering scaffold**, not a certified crowd safety model. The map's curved seat rows, doorway locations, walkway clearances, lengths, and rates are provisional approximations based on the contest schematic rather than as-built survey measurements. Bodies are simplified 2D discs; full contact forces, crush loading, mobility-specific pathways, signed distance wall fields, time-continuous collision detection, real stair occupancy, and fire dynamics are *not* included. The sample policy makes no validated evacuation-time predictions.

The engine uses sequential, seeded randomized update order and proximity-grid collision tests. To implement more sophisticated simultaneous motion, contact pressure, or graph-based navigation, replace `step()`, `_move()`, and/or `insideRegion()` explicitly; they are normal, open JavaScript source.
