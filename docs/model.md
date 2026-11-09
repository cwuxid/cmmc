# Model definitions and geometry

These definitions apply to both engines. See the [Python instructions](../python/README.md) or [JavaScript instructions](../javascript/README.md) for execution and tests.

## Decision model

The implementation follows [image_2.png](images/image_2.png) and [image_3.png](images/image_3.png), with explicit operational definitions for otherwise unspecified features:

```text
utility(i, k, t) = distanceScale * distanceScore(i, k)
                 + congestionScale * congestionScore(i, k, t)
                 + behavioralScore(i, k, t)
                 + panicScale * panicScore(i, k, t)
                 + residual(i, k, t)

behavioralScore = -wTime * normalizedExpectedTime
                  +wHabit * familiarity
                  +wPeer * peerShare
                  -wNorm * normViolationProxy
                  -wSwitching * changedTarget
```

Each agent's **five behavioral weights** is an independent normal draw with mean **0.5**, variance **1**, and standard deviation **1**. These are untruncated draws, not probabilities or weights summing to one. Negative values reverse a term's usual preference: a negative time weight rewards longer perceived times; a negative switching weight rewards changing targets. Weights remain fixed throughout a run. These draws intentionally supersede the nonnegative-weight restriction in the second reference image.

Other parameters retain the bounded domains in the first reference image. They are auxiliary parameters, distinct from the five normal behavioral weights:

- Distance exponent: independently uniform in [0, 1).
- Congestion preference: independently uniform in (-1, 1).
- Panic susceptibility: independently uniform in [0, 1).

`Random.normal(mean, variance)` takes **variance**, not standard deviation. All random draws use one seeded pseudorandom generator, making the same configuration and seed reproducible.

### Operational definitions

- **Distance:** Manhattan distance to the closest cell of each exit. The score is `((minimumAvailableDistance + 1) / (distanceToThisExit + 1)) ^ betaDistance`. Distance is in abstract grid cells.
- **Observed crowd:** agents within a configurable Manhattan radius, counted by their target commitments from the previous step. At the first decision everyone is uncommitted, so all crowd counts are zero. Counts are local, not population-wide.
- **Congestion:** normalize observed exit counts to [0, 1]. Use `normalizedCount ^ betaCongestion` for a nonnegative parameter, and `(1 - normalizedCount) ^ (-betaCongestion)` otherwise. When counts tie, all congestion scores equal 1. As written in the reference formula, a positive parameter rewards crowded targets and a negative parameter rewards less crowded ones; this is not automatically a congestion penalty.
- **Expected time:** `(local distance + visible target count / exit width) / timeReference`. This is an observable delay proxy, not a prediction of the true future queue. The default reference is 10 abstract steps.
- **Habit:** 1 for a remembered entrance exit, 0 otherwise. Entrance exits are independently assigned uniformly among reachable exits; entry travel itself is not simulated.
- **Peer influence:** share of locally observed, committed agents choosing that target; 0 if nobody nearby has committed.
- **Norm violation proxy:** fraction of observed neighbors who have waited longer, are closer to this exit, and previously selected it. It represents potential queue conflict, not a claim that the movement is literal queue cutting. Replace this feature when an explicit social rule is specified.
- **Switching:** 1 if changing an established target, otherwise 0.
- **Panic:** `susceptibility * exitSpecificNormalDraw * (1 - exp(-time / panicTimeScale))`. One standard-normal draw per agent/exit is retained across decisions. This is a signed utility perturbation with growing magnitude; it does not itself increase walking speed. The default time scale is 100 steps. A target-independent additive panic term would cancel from the decision.
- **Residual:** independent normal draw, mean 0 and standard deviation 0.2, for each evaluated alternative at each decision.

Distance and expected time both enter utility, following the supplied formulation. To isolate their contributions, set `distanceScale`, `congestionScale`, or `panicScale` to zero in the configuration. The five normal weights are left unchanged.

Highest utility wins, with random tie-breaking. By default, 2% of decisions instead explore a random available exit; set `explorationProbability` to 0 for strict utility maximization. A target is retained until exit or sustained blockage. Blocked agents reconsider after 10 blocked steps and no more often than every 8 steps. There are no intermediate junctions in an empty square room.

## Movement and interaction

Each cell can contain at most one person. Each person can move one orthogonal cell per step. Agents request an unoccupied neighboring cell that reduces navigation distance to their chosen exit. A contested cell selects a winner uniformly at random, independent of utilities or agent IDs; with probability `conflictFriction` (default 0.05), nobody moves into that contested cell.

All observations use the same starting positions and old target commitments. All movement requests are generated before any movement occurs. An occupied cell cannot be entered even if its occupant moves away during this step. This conservative rule prevents swaps and overtaking but can create extra delay and persistent blockage at high density. Exit cells admit at most one person per cell per step; arrivals are removed immediately. There is no pushing, contact force, continuous velocity, or explicit voluntary yielding in this version.

Every active step is recorded as either one move or one waiting step per person. Runs stop at full clearance or `maxSteps`. A step-limit run reports remaining participants and a null clearance time; it is never labeled complete. Mean and 95th-percentile exit times describe **exited participants only**, whereas mean waiting includes all participants.

## Building geometry: working extension section

Expand **Geometry & model configuration** in the simulator. Edit and apply its JSON. [shared/building-example.json](../shared/building-example.json) supplies a square with a central rectangular obstacle. Coordinates are zero-based; x increases right and y increases down. Boundary walls occupy coordinate 0 and `size - 1`.

```json
{
  "participants": 150,
  "seed": 42,
  "maxSteps": 10000,
  "geometry": {
    "type": "square",
    "size": 31,
    "exitWidth": 1,
    "obstacles": [
      { "x": 13, "y": 8, "width": 3, "height": 15 }
    ]
  }
}
```

For custom doors, add an `exits` array to `geometry`. Explicit exits replace the four default doors and override `exitWidth`:

```json
"exits": [
  { "name": "North door", "cells": [{ "x": 15, "y": 0 }] },
  { "name": "East door", "cells": [{ "x": 30, "y": 15 }] },
  { "name": "South door", "cells": [{ "x": 15, "y": 30 }] },
  { "name": "West door", "cells": [{ "x": 0, "y": 15 }] }
]
```

For this 31-cell example, put doors on a boundary wall away from corners. Add adjacent boundary cells to widen a door. Obstacles must fit inside the interior. Disconnected interior regions without any reachable exit are rejected.

Three extension points in [JavaScript](../javascript/model.js) and [Python](../python/auditorium.py) keep the building separate from behavior:

1. **`Building`:** generates walkable cells, exits, connectivity, and navigation fields. Replace or extend it to introduce rows, aisles, room outlines, and physical cell dimensions.
2. **`Simulation.observe`:** defines visibility and available information. Currently neighborhood observation uses distance only and does not account for wall occlusion. Introduce line of sight, signage, memory, and locally discovered targets here.
3. **`Simulation.evaluate`:** maps observations to utilities. Add intermediate waypoints or change behavioral features here.

**Navigation knowledge assumption:** movement currently uses simulator-computed shortest-distance fields to the selected exit to get around obstacles. Utility distance remains Manhattan distance and congestion remains local, but this movement layer assumes navigation assistance/known routes. It is not a model of discovering an unfamiliar obstructed building. Replace navigation fields with local waypoint discovery or exploration before interpreting obstacle experiments as fully partial-information behavior. In the initial empty square, unobstructed routes do not require that distinction.

No cells-to-meters or steps-to-seconds conversion is assumed. Geometry, occupancy, and service rules are still parameters even in an abstract model; this is a behavior experiment before physical calibration.

