# Local behavioral model implementation

Historical change log: the later familiarity-removal revision supersedes all references below to five-factor utility and familiarity rewards. Current utility uses four weights (T, P, N, S); see [FAMILIARITY_REMOVAL.md](FAMILIARITY_REMOVAL.md).

The current two-plan default now implements the remaining behavioral features.
`behaviorMode: "local"` selects it. Archived source geometry still uses the
original policy, with its separate `legacyDecisionInterval` of 1.5 seconds.
On current geometry, `behaviorMode: "legacy"` permits behavioral comparisons.

## Complete functional change list

| Component | Change and effect |
|---|---|
| `arrival.py` (new) | Records an explicit exterior-to-seat admission path for every unit. Familiarity comes from membership in this path, including its final row side. |
| Admission reconstruction | Default `arrival.defaultEntrance` is `M2`. A deterministic reverse-topology traversal constructs a feasible admission path to each occupied section and an adjacent row aisle. This consumes no extra random draws and is labeled `reconstructed`. It is an assigned admission record, not simulated pre-emergency walking or measured historical behavior. |
| Recorded admission paths | `arrival.routesBySeat` accepts actual recorded portal sequences and optional row side, keyed by seat label. These are labeled `recorded`. Route order, exterior entry, adjacency, and destination section are checked. Unknown seat labels are rejected at world validation. |
| `perception.py` (new) | Filters observations using a finite sight distance, configurable viewing angle, floor, and wall occlusion. Moving velocity supplies facing; stored heading is used when stationary. |
| Schematic occlusion | Orchestra barrier material, its six openings, the corridor's inner auditorium wall and AUD openings, foyer walls and F/M apertures, and optional explicit wall segments affect sight. Circular walls occupy only their semicircles. Closed apertures block sight through them. |
| `geometry.visibilityWalls` | Accepts extra floor-specific line segments for observation occlusion. They are validated. These are visibility geometry, not extra body-collision walls; body mechanics still use the existing plan geometry. |
| Perceived action set | Offers visible eligible targets, targets remembered from admission or previous observation, and the current target. It does not offer every hidden unknown door in the current region. Being remembered does not mean a target is currently visible. |
| Local search | When no portal is perceived or remembered in a curved circulation region, offers short left/right exploration targets based on region bounds, without consulting hidden door positions. If no action is offered elsewhere, a stationary unit changes its scan heading on the next decision. |
| `behavior.py` (new) | Defines one action as one next physical target: a row end, aisle continuation, door, access opening, stair entrance, or local exploration waypoint. A completed stage leads to a new local decision. |
| `MAIN` aggregation removed from decisions | Corridor choices are actual `F0/F1/F2` doors or side thresholds. `MAIN` remains the completion-category label for the five final foyer doors; it is not a candidate route followed by a separate nearest-door choice. |
| `MAIN` compatibility bug fix | In current geometry's optional legacy behavior, only door-type corridor portals count as foyer entrances when estimating/following MAIN. Side exits cannot accidentally be used as foyer entries. Archived geometry is left unchanged for source parity. |
| Initial row choice | Both available row directions are scored by utility. Initial facing/row memory no longer decides which aisle is used; they only initialize observation and familiarity state. |
| Foyer entrance choice | Foyer entry doors compete directly against other local corridor actions in utility maximization. No distance-only intermediate choice remains in local mode. |
| Stable target identity | `data.targetId`, `targetStage`, and `localAction` identify the commitment. Switching cost is one for abandoning another target in the same stage and zero for keeping it or beginning a genuinely new stage. |
| Safe late door changes | Rectangular exit waypoints first retreat to the interior when a changed target leaves the person in a neighboring doorway's apron, then align with the chosen opening before crossing. This resolves a wall-edge dead zone without overriding target choice or accepting an invalid crossing. |
| Reconsideration timing | Row, aisle, rim, balcony-rim, corridor, foyer, and stage-landing decisions all use `decisionInterval`. The user's requested 3-second default is retained; set it to 1 for once-per-second decisions. Physical stage changes and discovered target closures trigger fresh decisions. Timed stairs remain transfers rather than decision planes. |
| Frozen behavioral observations | At each tick start, visible-agent input records are copied into a spatial index. Peer and queue cues do not change with randomized movement order later in that tick. Body-force calculations and physical motion retain their existing sequential mechanics. |
| Directional peer share | `P` is the proportion of observed nearby agents whose intended local direction is within the configured angular tolerance of the candidate direction. Different target IDs can therefore indicate the same flow. Stationary agents with an intended direction can count; uncommitted idle people remain in the denominator. |
| Queue observation | A started unit moving slowly within the queue-observation distance of its selected portal gets a queue target and first-wait timestamp. Leaving that queue, changing target, or moving out of the waiting condition clears the timestamp. Same-time priority uses ID as a deterministic tie break. |
| Queue-cutting perception | A candidate is penalized if joining it would put the unit closer to the portal than people observed waiting there with earlier priority. Queue-cutting score is the fraction of those prior waiting people it would jump ahead of, with a body-clearance margin. This includes stationary queues. |
| Norm feature | `N` is the maximum of perceived queue cutting and the observed opposing-motion fraction, bounded between zero and one. It is a concrete operational norm model, not a complete account of all social norms. |
| Local travel-time feature | `T` uses estimated travel to the next local target divided by preferred speed and `timeScale`. It no longer appends an entire stair-flight traversal to the time to reach that stair entrance. |
| Optional perceived queue delay | Enabled by default. Observed earlier-priority waiters ahead contribute an estimated wait of count divided by `portal.width * 1.3`, matching the engine token-refill scale. No hidden/global queue count is queried. `perceivedQueueDelay: false` disables this feature refinement. |
| Experienced row blockage | A unit stopped by an observed opposing person in the same narrow seat row estimates future wait from its experienced blocked duration plus one decision interval, multiplied by `rowBlockWaitFactor`. Only the obstructed candidate direction receives this delay. This prevents a free-flow estimate from remaining unchanged through a long visible standstill; it does not force a target change or relax body constraints. It is a configurable prediction heuristic, not a measured queue model. |
| Global crowd reward removed | Local utility has no standalone reward based on population-wide commitment counts. Local peer influence remains in the weighted behavioral vector. |
| Behavioral dot product | Exposes `behavioral_utility(weights, features) = -wT*T + wH*H + wP*P - wN*N - wS*C`. Weights remain sampled once from the existing joint unit-mean lognormal distribution. |
| Full utility retained | The earlier specified normalized-distance term, panic, and residual shock are retained alongside the behavioral component. `behavioralOnly: true` selects the five-feature dot product alone and avoids drawing panic/residual shocks. |
| Decision diagnostics | `data.lastDecision` exposes each offered action, next target, perception source, T/H/P/N/C features, travel/queue seconds, peer counts, queue-cut/counterflow components, utility terms, current target, and winning action. `globalCrowdTerm` is explicitly zero. Existing inspection and JSON export expose this data. |
| Input validation | Validates behavioral mode, Boolean switches, time/observation scales, angular bounds, admission configuration, and explicit visibility segments. |
| `behavioral_only_settings.json` (new) | Runnable settings override for comparing the five-feature behavioral component alone. |
| Tests | Adds manuscript-example and integration regressions for admission memory, sensing, directional peer share, stationary queue cutting, local wait estimates, utility-based row/F choices, MAIN correctness, reconsideration, unchanged weights, diagnostics, and independence from global counts. Existing rare-route tests now check explicit admission memory rather than universal MAIN familiarity. |
| Documentation and results | README explains the controls and new module boundaries. This file enumerates all functional changes. `results/local-behavior-*` saves verification runs without replacing previous branch baselines. |

## Configuration

New default policy settings:

```json
{
  "behaviorMode": "local",
  "decisionInterval": 3,
  "legacyDecisionInterval": 1.5,
  "visionRange": 12,
  "fieldOfViewDegrees": 360,
  "peerDirectionToleranceDegrees": 45,
  "queueObservationDistance": 3,
  "queueSpeedThreshold": 0.25,
  "rowBlockWaitFactor": 1,
  "perceivedQueueDelay": true,
  "behavioralOnly": false
}
```

Distances are metres, times seconds, angles degrees, and queue-speed threshold
metres/second. A 360-degree field of view assumes people can look around; set a
smaller angle to study forward-facing observation. `observeRadius` (4 m) still
limits nearby-person cues. `visionRange` (12 m) limits newly observed targets.
Remembered target locations remain available outside the instantaneous field of
view. The observation model does not include body/seat occlusion or eye height.

World input accepts:

```json
"arrival": {
  "defaultEntrance": "M2",
  "routesBySeat": {}
}
```

Find a unit's real `seat.label` and `data.arrivalMemory` in the inspector or full
JSON. To supply measured ingress, add that seat label to `routesBySeat`, using:

```text
"<actual seat label>": {
  "portals": [<exterior threshold, then connected portals toward the seat>],
  "rowSide": "ROW_LEFT" or "ROW_RIGHT"
}
```

Use the actual IDs in this building: M doors -> F doors -> AUD doors -> ACCESS
openings for orchestra seats; M -> F -> AUD for loge; M -> BACK stairs for
balcony. Side and stage routes can also be supplied if their reverse topology
connects to that seat. An orchestra route's final ACCESS must match its row side.

Additional visibility walls are a list in the world's `geometry` object:

```json
"visibilityWalls": [
  {"floor": 0, "start": {"x": 1, "y": 37}, "end": {"x": 1, "y": 39}}
]
```

This example is a hypothetical occluder, not a claim about Bailey Hall.

## Running and reviewing

From the Python project directory:

```powershell
python run.py --gui
python run.py --population 300 --seed 2026 --max-seconds 180
python run.py --population 30 --settings behavioral_only_settings.json
python -m unittest discover -s tests -v
```

Restart an already-open GUI to load new modules and defaults. In the inspector,
compare `arrivalMemory`, `targetId`, `lastDecision`, and `socialForce` to see the
full chain from remembered admission route to perceived features to physical
motion. Per-person feature rules are identical; weights change their influence.
Individual geometry, history, preferred speed, and observations can still yield
different feature values, as allowed by the individual-indexed specification.

Social-force equations, body constraints, reaction delays, stair transfers,
seat inventories, and first-floor threshold completion are retained. Model
features are operational assumptions and remain uncalibrated. Recorded arrival
paths and more detailed visibility geometry can replace reconstruction without
changing the behavioral utility equation. The code simulates these assumptions;
it does not fit behavioral weights from observed evacuation data.

## Verification

All 88 headless tests and the actual hidden-window Tk desktop test pass (89
total). The 27 new behavioral tests reproduce all six manuscript examples,
verify the observation/feature rules, exercise every decision region at both
one- and three-second intervals, and cover opposing row blocks and late door
changes. Archived JavaScript-reference tests continue to pass.

With the user's retained three-second default, 300-person runs fully clear in
approximately 67.6 seconds (seed 2026) and 70.6 seconds (seed 7). The sampled
traits and utility weights match the corresponding pre-change populations.
All 600 final threshold records are on the first floor, and every exported
last-decision behavioral value, full utility sum, and maximizing action has been
checked. See `results/local-behavior-verification.json` and
`results/local-behavior-verified-300-seed2026.json` / `...seed7.json`.

Earlier `local-behavior-*` probes preserve intermediate diagnostic states;
filenames containing `verified` identify the final implementation. These
outcomes describe the assumed model and are not calibrated evacuation times.

The full-capacity stress probe completed before the later request to limit
further runs to 300 participants: 1,163 of 1,329 exited by 300 simulated seconds,
with 166 remaining and a null clearance time. That result is retained in
`results/local-behavior-verified-full-house.json`; the completed behavioral
implementation does not imply that every crowded realization clears. Further
assistant simulation runs are restricted to n = 300 as requested.
