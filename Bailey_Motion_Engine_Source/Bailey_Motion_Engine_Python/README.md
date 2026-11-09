# Bailey Motion Engine — Python port

This Python model began as a port of the **Bailey JavaScript project in the sibling `Bailey_Motion_Engine/` directory**. Its default geometry now implements the supplied two-floor description and plan connectivity. The original JavaScript geometry remains available as `bailey_motion/legacy_world.json` for historical comparisons. The JavaScript source and the older square-room model at `../../python/` have not been changed.

Python 3.10+ is required. The engine and command-line runner use only the standard library. The optional desktop interface needs Python's Tcl/Tk support; there are no pip dependencies.

The detailed mathematical description is available as [BUILDING_SPECIFICATION.tex](BUILDING_SPECIFICATION.tex), a standalone LaTeX document covering building geometry, seating, region constraints, perception, current four-factor utility, forces, transfers, and exit accounting.

The whole-model parameter reference is [MODEL_PARAMETERS.md](MODEL_PARAMETERS.md), with a LaTeX version in [MODEL_PARAMETERS.tex](MODEL_PARAMETERS.tex). It identifies units, defaults, applicable modes, fixed implementation constants, and legacy or inactive settings.

## Optional LED route strips

Enable **LED route strips (apply/reset)**, set **LED strength (utility bonus)**, and click **Reset / apply controls**. Green directed strips show the reference shortest-exit network on each floor, including curved rows and circulation routes. The lighting adds a **constant utility bonus** to its indicated next action. It does not add physical acceleration or convert the audience into students; existing behavioral preferences can outweigh its advice.

The default strength is **12 utility units**, matching the default manager bonus at zero distance. LED strength does not decay with separation or time. Setting it to zero removes its behavioral and target-discovery effects. The GUI can still display strips at zero strength; `showStrips: false` hides them without changing behavior.

```powershell
python run.py --n 300 --led-strips --led-strength 12 --gui
python run.py --n 300 --led-strips --led-strength 6 --max-seconds 120
python run.py --n 300 --led-settings led_settings.json --gui
python run.py --n 300 --led-settings led_settings.json --no-led-strips
```

LEDs are off by default. `--led-strength` alone sets a value but does not enable the mode. The `ledStrips` world object has `enabled`, `strength`, `adaptive` and `showStrips` fields; see [led_settings.json](led_settings.json) for an opt-in example.

With `adaptive: true`, the controller assumes instantaneous information about disabled evacuation portals and reroutes its lighting on the next simulation tick. People receive a new cue at their next decision; they are not given a global list of closures. With `adaptive: false`, the controller freezes its initial availability map, so later blockages can make directions stale. Continuous strip coverage is assumed; photometry and smoke attenuation are not modeled.

**Student mode suppresses LEDs and crowd managers.** Their preferences are retained for a later nonstudent reset. For nonstudents, LEDs can operate alone or with explicitly enabled managers; both utility bonuses then add. Enabling LEDs does not create staff. The GUI and exported decisions identify LED strength, recommendations, compliance and choices changed by the LED bonus. Read [LED_GUIDANCE.tex](LED_GUIDANCE.tex) for the mathematical specification and file-by-file code explanation, without results tables.

## Optional student audience

Enable **Students: shortest routes (apply/reset)** in the GUI, then click **Reset / apply controls**. Every guest then knows the building layout and deterministically chooses a shortest remaining route by graph distance. Behavioral weights, peer following, switching costs, queue estimates and utility noise do not select their route. Reaction delays, preferred speeds, collision avoidance, door capacities and stair queues still apply.

**Student mode suppresses crowd managers and LED guidance completely**, even if their checkbox or CLI flag is selected. The GUI disables these guidance controls while retaining their preferences for later. Turning students off and resetting restores the selected settings. No staff bodies, manager instructions or LED bonuses affect student runs. Explicit physical closure schedules remain active without staff notifications; students learn unexpected closures locally rather than receiving global knowledge.

```powershell
python run.py --n 300 --students --gui
python run.py --n 300 --students --max-seconds 120 --output results/student-example.json
# Still no active managers: student mode takes precedence.
python run.py --n 300 --students --crowd-managers --gui
# Override studentMode in a loaded world.
python run.py --config my_world.json --n 300 --no-students --gui
```

For world JSON use `"studentMode": true`; the flag is absent/off by default. The same distance graph used for manager recommendations maps every seat to an initial route and supports recomputation from current position. Student decision records expose route lengths, selected exits and unreachable states. This is a shortest-distance policy, not a guarantee of the fastest evacuation. Crowd-manager placement searches reject student-mode worlds because staff are inactive. See [STUDENT_MODE.tex](STUDENT_MODE.tex) for the mathematical specification.

## Optional six-crowd-manager experiment

**Crowd managers are disabled by default.** The ordinary world, its four behavioral weights and its 3-second decision interval remain the baseline. Enable six stationary managers through the GUI checkbox **Six crowd managers (apply/reset)**, then click **Reset / apply controls**, or use the optional CLI arguments below. Disabling the checkbox and resetting removes staff and their behavioral influence.

Run these commands from this Python project directory using your installed Python. The launcher scripts also support an isolated interpreter and execution from another working directory; input JSON filenames remain relative to your current shell directory.

```powershell
# Ordinary model: no managers.
python run.py --n 300 --gui

# Explicitly enable six managers with an automatically initialized placement.
python run.py --n 300 --crowd-managers --gui

# Guided headless run with separate manager assumptions.
python run.py --n 300 --manager-settings crowd_manager_settings.json --max-seconds 180 --output results/guided-example.json

# An exit closes at 10 s; automatic staff notification follows 15 s later.
python run.py --n 300 --manager-settings crowd_manager_blocked_example.json --max-seconds 180 --output results/guided-blocked-example.json

# Keep the same scheduled blockage but remove managers for comparison.
python run.py --n 300 --manager-settings crowd_manager_blocked_example.json --no-crowd-managers --max-seconds 180
```

Output files must be new files inside this project, so use another filename when repeating an exported run. `--crowd-managers` and `--no-crowd-managers` override the enabled flag in a loaded world or manager settings file. A settings file replaces the world's `crowdManagers` object; unspecified manager fields use documented defaults.

The route graph assigns an all-open shortest reference route to all 1,329 seats. Directions later use current position and the closures known to the manager/guest. Same-floor, wall-occluded communication decreases exponentially with distance. A guest prefers its initially assigned manager whenever that manager's instructions can be received, even if another manager has a stronger signal. Otherwise it uses the strongest reachable manager, retaining its original assignment. The selected instruction adds a utility bonus and reveals its next target. Remembered portal sequences continue across regions until expiry or invalidation. Finite authority permits noncompliance; it does not change the original four sampled weights.

Staff occupy physical space and affect collision avoidance, but they are separate from the 300 audience members and from behavioral peer statistics. Initial placement uses coverage, not a completed evacuation-time optimization. Manager triangles, optional range outlines (`showCoverage` in manager settings), the selected person's route text, inspector state and full JSON provide diagnostics. The coverage circle is only a range limit; walls still occlude actual communication.

The GUI explicitly displays **Managers OFF** or **Managers ON: 6**, people reached, guided decisions and choices changed by the guidance bonus. The latter compares each actual decision with scoring the same offered actions after subtracting only the guidance bonus; it is not a complete no-manager counterfactual. On completion, the GUI shows interpolated clearance and time to 95% exited to three decimals, separately from the one-decimal tick clock. Restart an already running GUI after source edits so imported modules are refreshed.

Saved initial search/timing results in the write-up used the earlier strongest-signal selection rule. They have not been rerun for assigned-manager priority. New guided summaries identify the rule as `managerSelection: "assigned-first"`; a new placement search evaluates that current rule automatically.

### Search for six-manager placements

```powershell
# Small pipeline check: 3 initial layouts, 1 generation, one training audience.
python optimize_crowd_managers.py --n 300 --search-population 3 --generations 1 --max-seconds 120 --training-seeds 2026 --validation-seeds 7 --output results/search-example.json --layout-output results/selected-manager-layout.json

# Larger search across open, immediately known and delayed-blockage scenarios.
# These are equal-weight experimental scenarios, not measured probabilities.
python optimize_crowd_managers.py --n 300 --manager-settings crowd_manager_settings.json --scenarios crowd_manager_scenarios.json --search-population 8 --generations 5 --training-seeds 2026 17 29 --validation-seeds 7 31 --max-seconds 180 --output results/scenario-search.json --layout-output results/scenario-layout.json

# Inspect the selected placement in the normal GUI.
python run.py --n 300 --manager-settings results/selected-manager-layout.json --gui
```

The larger example can require many simulations. The maximum number of training simulations is `(P + K*(P-1))*R*S`, where P is search population, K generations, R training seeds and S scenarios; the cache may reduce it. Held-out comparisons add `2*V*S` simulations. Search progress prints each evaluation. The search is an optional separate command and never starts when launching the GUI.

The genetic search evaluates six distinct feasible candidate locations, varies the allocation between floors, retains an elite and caches repeated layouts. By default, at least one manager must serve each floor; `requireBothFloors: false` removes that constraint. Parameters controlling authority and communication stay fixed during the search.

The objective ranks layouts lexicographically by **failure probability, mean fraction remaining, then mean restricted clearance time**. Incomplete runs remain in the report with actual clearance time `null`; they cannot win by evacuating only the fastest people. With every run complete, the time objective is mean total clearance time. Training seeds choose the layout; disjoint held-out seeds evaluate it against the same audience without managers. The optimizer uses counter-keyed behavioral shocks and matched initialization fingerprints. For manual paired experiments, use a policy settings override `{"pairedRandomness": true}` in both runs. Ordinary runs retain their original RNG behavior.

Each closure targets a named portal. `notifyAfter: 0` provides immediate staff news; a positive delay postpones news; `null` disables automatic news. Local discovery or a guest report may inform staff sooner. Closing all five main doors requires five events (`M0` through `M4`), whereas closing `M2` closes only that threshold. The schedule currently supports permanent complete closures, not reopening or partial throughput reductions.

If no `--scenarios` file is supplied to the optimizer, it uses the closure schedule in the loaded manager settings (or all-open conditions when that schedule is empty). An explicit scenario list overrides that schedule for evaluation. Adherence diagnostics include single-action stages and should not be interpreted as an independently calibrated obedience probability.

Read [CROWD_MANAGERS.tex](CROWD_MANAGERS.tex) for the graph metric, full utility, physical coupling, memory, information model, optimization objective, random-number pairing and research provenance. It also contains the exact experimental configuration and tables of the initial GUI-configuration reproduction, paired comparisons, and held-out placement-search results, including the slower blocked-exit cases. [CROWD_MANAGER_CHANGES.md](CROWD_MANAGER_CHANGES.md) lists functional changes. The default coefficients are experimental assumptions, and a small search returns a **best-found placement on the schematic map**, not a globally optimal or calibrated venue evacuation plan.

## Current two-plan layout and completion rule

The default world has **two independent physical plans**, with connections defined by named departure portals and corresponding destination entrances. Bodies on different plans never collide simply because they share coordinates. A transferred participant retains the same ID, starting-seat record, sampled preferences, and accumulated transfer history.

A generated [two-plan layout preview](results/two-plan-layout.svg) shows the current schematic geometry without pedestrians.

| Part of the layout | Implemented topology |
|---|---|
| Orchestra | 527 seats on the first-floor plan |
| Elevated loge/mezzanine | 486 seats on the first-floor plan, separated from the orchestra by a barrier |
| Orchestra-to-loge connections | Six controlled access points, `ACCESS1` through `ACCESS6`, landing at `LOGE_ACCESS_1` through `LOGE_ACCESS_6` |
| Regular auditorium doors | Nine doors, `AUD0` through `AUD8`, from the loge-side rim to the semicircular corridor |
| Corridor-to-foyer doors | Three interior doors, `F0` through `F2` |
| Main exterior doors | Five thresholds, `M0` through `M4`, aggregated as final exit `MAIN` |
| Side exterior doors | Four available thresholds, `SIDE_E1`, `SIDE_E2`, `SIDE_W1`, and `SIDE_W2` |
| Balcony | 316 seats on the separate second-floor plan |
| Rear balcony staircases | `BACK_E` and `BACK_W`: each has two flights, a divider, and two independent FIFO lanes; they land at `FOYER_BACK_E` and `FOYER_BACK_W` on the first floor |
| Stage-side balcony staircases | `STAGE_E` and `STAGE_W`: transfer to matching first-floor stage landings, then leave through `GROUND_STAGE_E` or `GROUND_STAGE_W` |
| Elevator | `ADA_W` is shown but excluded from evacuation; its UI switch is disabled and portal service rejects it |

There are exactly **1,329 participant places**, with no additional wheelchair agents or mobility subclasses. Body radii are identical in this default layout. Preferred speeds, reaction times, and behavioral preferences can still vary according to the configured distributions.

**An individual exits only when its center crosses an exterior threshold on the first-floor plan.** Leaving the balcony, crossing an auditorium door, passing through a foyer entrance, or entering stairs does not count as exiting. There are eleven final thresholds: five foyer, four side, and two first-floor stage thresholds.

Exit detection checks the actual movement segment against the finite-width threshold. It records the intersection position and interpolated time within the tick, rather than removing someone merely for approaching a door. Disabled or capacity-blocked thresholds prevent passage. The per-agent `exitThreshold` and exported `thresholdEvents` identify the exact main-plan threshold crossed.

The monumental outside stairs and the two portico-to-street stairs are shown as context only. They add no evacuation time because completion is defined at the first-floor exterior thresholds. Side doors and stage stairs remain available throughout the run, without a familiarity preference. They do not require an emergency-mode switch.

Typical routes are:

```text
Orchestra row -> orchestra aisle -> one of six loge access points
              -> loge aisle -> loge-side rim -> auditorium door
              -> corridor -> side exit OR foyer -> main exit

Loge row -> loge aisle -> loge-side rim -> auditorium door -> same first-floor routes

Balcony row -> balcony aisle -> balcony rim
            -> rear stairs -> matching first-floor foyer entrance -> main exit
            OR stage stairs -> matching first-floor stage entrance -> stage exit
```

### What is specified versus approximated

Seat totals, route connectivity, six barrier access points, door counts, two rear flights/lanes, elevator exclusion, and the completion rule follow the supplied description and plans. The footprint is still a **schematic metric model**, not a tracing or an as-built survey: seating rows are represented by circular arcs, and exact dimensions/individual seat labels have not been extracted from every annotation in the images.

Current editable approximations include a barrier radius of 16.9 m and width of 0.35 m, six 1.3 m access openings with 1.5 m traversal lengths, and rear stairs of two 7.5 m flights with 1.6 m total width and a 0.1 m lane divider. These are declared in JSON rather than asserted as measured dimensions. Each stair lane is a timed FIFO transfer with body-based admission spacing and finite occupancy; stair-body contact forces and continuous step-by-step motion on the flights are not modeled.

### Where to edit this geometry

In `bailey_motion/default_world.json`, `geometry.plans` identifies the plans, `zones` and `regions` define movement domains, `orchestraBarrier` defines the wall/openings, `portals` defines departures, and `entrances` defines corresponding arrival locations. Every nonfinal connection names a `toEntrance`. Destination floor, region, zone, position, and landing direction are explicit.

The validator rejects missing/mismatched entrance links, incorrect specified inventories, final exits on the balcony, an enabled evacuation elevator, and rear staircases without two separated lanes and two flights. Floor/zone changes cannot be performed through ordinary `set_region` calls; a transfer connection is required.

`planOccupancy`, `exitedByOriginPlan`, and `exitThresholdCounts` in summaries distinguish current occupancy from originating floor and final door. Individual `transfers` and full-run `transferEvents` record source portal, destination entrance, source/destination plan, lane, and timing. While in transit, `transit.flightsComplete` and `awaitingEntrance` show progress and blocked landings. Occupied destination entrances delay landing without duplicating or deleting participants.

## How to run your first experiment

### 1. Open a terminal in the Python port directory

In your IDE, open a PowerShell terminal and enter:

```powershell
cd C:\Users\casey\Desktop\modeling\Bailey_Motion_Engine_Source\Bailey_Motion_Engine_Python
```

The commands below assume that working directory. Run **`run.py`**, rather than running `bailey_motion/app.py` directly: the launcher sets up package imports and processes your options.

Check your interpreter, then launch the desktop interface:

```powershell
python --version
python run.py --gui
```

If the normal `python` command is unavailable, this workspace includes a local runtime. From the same directory, substitute it for `python`:

```powershell
..\..\.python-runtime\python.exe run.py --gui
..\..\.python-runtime\python.exe run.py --population 30 --ticks 100
```

That runtime is machine-specific and reads the existing installed standard library. A desktop session also requires working Tcl/Tk; command-line experiments do not. See [Troubleshooting](#troubleshooting) if the window cannot open.

### 2. Inspect and run the desktop simulation

The window starts **paused** with a default population of 300. It shows the main floor and balcony, using the same physical coordinates as the JavaScript version.

1. For a small first experiment, enter `30` in **Population** and click **Reset / apply controls**.
2. Leave **Seed** at `2026` and **dt (s)** at `0.1`.
3. Click **One tick** or **10 ticks** to inspect incremental changes.
4. Click **Run** to begin playback, and **Pause** to inspect a developing queue.
5. Click a pedestrian to show its record in **Inspector / errors**. Expand your reading of `data` to see its sampled `weights`, selected portal, route choice, known closed doors, and cached shocks.
6. To start again from time zero, click **Reset / apply controls**. With the same seed, settings, and sequence of interactions, the experiment is reproducible within Python.

People wait for their sampled reaction time before starting. They then travel through rows, aisles, circulation areas, doors, and possibly stairs. Colors indicate their current region, not personality or preferred exit.

| Control | What it changes | When it takes effect |
|---|---|---|
| Population, Seed, dt | Population sampling and integration settings | After **Reset / apply controls** |
| Hard collisions | Rejection of overlapping body discs | After **Reset / apply controls** |
| Region constraints | Enforcement of row/aisle/circulation boundaries | After **Reset / apply controls** |
| Door capacity | Token-based doorway throughput | After **Reset / apply controls** |
| Playback | Simulated seconds per wall-clock second | During playback; does not change physics per tick |
| Enabled portal checkboxes | Whether particular doors/stairs can be used | Immediately; agents still discover closures locally |
| Editor contents | Candidate source, world, or coefficients | After the corresponding Apply button; resets the experiment |

A tick is `dt` simulated seconds. At `dt = 0.1`, 100 ticks represent 10 seconds. Increasing playback makes the display advance faster; changing dt changes the numerical experiment.

### 3. Run without a window

A short terminal experiment:

```powershell
python run.py --population 30 --seed 2026 --ticks 1000
```

This advances at most 1,000 ticks (100 seconds at the default dt), prints a JSON summary, and returns. It stops earlier if everyone exits or the world time limit is reached.

To run until clearance or a specified simulated-time limit, omit `--ticks`:

```powershell
python run.py --population 100 --seed 2026 --max-seconds 300
```

The default time limit is 1,800 simulated seconds. Existing policy blockages can leave people inside. Population is limited to the configured seat inventory, which totals **1,329** in the default building. Changing population does not automatically resize this building.

### 4. Save results and understand paths

Choose fresh output filenames for each experiment:

```powershell
python run.py --population 30 --seed 2026 --max-seconds 120 --output results/experiment-001.json --csv results/experiment-001.csv --include-weights
```

The files appear under this port's `results/` folder. You can open the CSV in a spreadsheet and the JSON in your editor or an analysis script. Existing files are never overwritten.

You can also supply these flags with `--gui`: the CLI saves the final displayed experiment **when you close the window**. If you close before clearance, it saves the partial state. To save while keeping the window open, use its export buttons instead.

| Path option | Resolved relative to |
|---|---|
| `--config`, `--settings`, `--policy` | Your terminal's current working directory |
| `--output`, `--csv` | This `Bailey_Motion_Engine_Python/` directory, regardless of terminal location |
| Desktop export buttons | Your selected filename, which must stay inside this Python port |

Output parent directories must already exist. The supplied `results/` directory is ready to use.

### 5. Read the summary and individual records

| Output field | Interpretation |
|---|---|
| `time`, `ticks` | Elapsed simulated seconds and integration-step count |
| `population`, `exited`, `remaining` | Initial participants and current completion counts |
| `clearanceTime` | Total clearance time, or `null` when anyone remains |
| `meanExitTimeAmongExited` | Average exit time for those who exited; excludes people still inside |
| `exitCounts` | Counts by final exit identifier |
| `remainingRegions` | Where unfinished participants currently are |
| `metrics.blockedMoves` | Rejected motion requests |
| `metrics.collisionRejections`, `regionRejections` | Failed clearance queries, including alternative trial positions; not unique people or physical impact counts |
| `metrics.portalWaits` | Unsuccessful portal capacity, stair-lane admission, or landing attempts |
| `planOccupancy`, `exitedByOriginPlan` | Current unfinished population by plan/transit and completed population by originating plan |
| `exitThresholdCounts` | Counts by exact exterior threshold, including individual main doors |

`status: "complete"` means full clearance. `status: "time_limit"` means the world time limit stopped the experiment. A deliberately bounded run can have `status: "running"` with `stopReason: "tick_limit"`; closing an unfinished GUI adds `stopReason: "window_closed"`.

Process exit code **0** means clearance, **2** means an incomplete experiment, and **1** means an error. Exit code 2 is expected for many short runs and is not, by itself, a crash.

Source-format CSV contains one row per person with its seat, final/current position, sampled traits, region, and exit information. `--include-weights` adds `wT`, `wP`, `wN`, and `wS`; otherwise those four utility weights are absent from CSV. Blank exit fields mean the person has not exited.

Full JSON includes configuration, policy settings and source, all agents including their custom `data`, portals, metrics, and retained history/events. It does not record every historical coordinate. Aggregate history retains the latest 2,000 samples, taken every ten ticks; the event log retains the latest 150 messages.

Current behavior diagnostics include `data.arrivalMemory` (admission route and whether it was recorded or reconstructed), `targetId` (next physical target), and `lastDecision` (all offered targets, observed features, utility components, and the winning target). `data.socialForce` separately records the latest force-derived motion calculation.

## How to change the model

### Change behavioral weights and policy coefficients

In the desktop **Policy settings** tab, change coefficients and click **Apply settings + reset**. For example, reducing `weightSigma` from `1.2` to `0.6` makes weights more concentrated while preserving their theoretical componentwise mean of 1.

For a terminal experiment, create `results/weights-example.json` in your editor with:

```json
{
  "weightSigma": 0.6,
  "weightRho": -0.15
}
```

Then run:

```powershell
python run.py --population 30 --settings results/weights-example.json --ticks 1000
```

Settings files can contain just the overrides you want; omitted policy settings use bundled defaults.

| Setting | Meaning |
|---|---|
| `weightSigma` | Standard deviation of each latent normal log-weight; must be greater than zero |
| `weightRho` | Correlation between latent log-weights; must be strictly between -1/3 and 1 |
| `timeScale` | Seconds used to normalize the perceived-time feature |
| `behaviorMode` | `"local"` (default) uses perceived next-target actions; `"legacy"` retains the previous behavior for comparisons |
| `behavioralOnly` | Use only the four-feature behavioral dot product; default `false` retains the distance, panic, and residual terms |
| `decisionInterval` | Reconsideration interval in every current-plan decision region; default `3` seconds, retained at the user's request; set to `1` for once-per-second decisions |
| `legacyDecisionInterval` | Archived geometry's source-parity interval, default `1.5` seconds |
| `visionRange`, `fieldOfViewDegrees` | Distance and viewing angle for newly observed targets; defaults `12` m and `360` degrees |
| `peerDirectionToleranceDegrees` | Angular tolerance for observed intended flow, default `45` degrees |
| `queueObservationDistance`, `queueSpeedThreshold` | Waiting-at-a-portal detection limits; defaults `3` m and `0.25` m/s |
| `perceivedQueueDelay` | Add visible queue delay and experienced opposing-row-blockage delay to perceived time; default `true` |
| `rowBlockWaitFactor` | Scale on the experienced opposing-row wait estimate; default `1`, use `0` to disable that part |
| `noiseInterval`, `shockSD` | Shock refresh interval in seconds and shock standard deviation |
| `observeRadius`, `discoveryRadius` | Peer-observation and selected-door closure-discovery distances in metres |
| `panicMean`, `panicSD` | Parameters for sampled panic susceptibility when not specified in world distributions |
| `relaxationTime` | Response time toward preferred velocity, in seconds |
| `socialForceMode` | `"manuscript"` (default) uses the supplied three-force equations for current plans; `"legacy"` retains the previous force calculations |
| `obstacleStrength` | Obstacle acceleration coefficient `A` |
| `comfortDistance` | Default individual obstacle comfort distance `r_i`, in metres; must be positive |
| `interactionLambda`, `interactionN`, `interactionNPrime` | Relative-velocity and angular coefficients in the interpersonal force |
| `interactionRange` | Neighbor-search cutoff for the interpersonal force sum, in metres; default `2.6` |
| `interactionStrength` | Extra acceleration multiplier in legacy force mode only; the supplied equation has coefficient one |
| `localAvoidance` | Enable target-preserving local collision avoidance outside seat rows; default `true` |
| `avoidanceLookahead` | Neighbor collision-prediction horizon in seconds; default `0.65`, must be positive |
| `passingClearance` | Additional passing comfort margin in metres; default `0.04`, must be nonnegative |
| `progressTimeout` | Time without 0.12 m of progress before trying alternative legal velocities; default `2.0` seconds |

The four positive lognormal weights are generated **jointly once per person**, with expected vector `(1, 1, 1, 1)`. Their order is time, peer influence, social norms, and switching. Familiarity/habit has been removed from utility, feature records, weight sampling, and weighted CSV output in both runtime behavior modes. They are not probabilities and do not sum to a fixed total. A finite population's sample averages need not equal one exactly. `weightRho` describes correlation before exponentiation, not the final weight correlation.

World traits such as `speed`, `reaction`, `radius`, `sanity`, `groupthink`, and `norms` are separate sampled parameters. Their distribution specifications use `sd` (standard deviation), not variance. The sampled `norms` trait scales interaction acceleration only in legacy force mode; manuscript mode follows the supplied equation without that multiplier. It is separate from utility weight `wN`.

`groupthink` remains sampled for legacy compatibility, but its former standalone global-crowd reward is inactive in local behavior mode. The fixed `wP` weight controls sensitivity to the observed directional peer feature.

### Local behavioral features and route memory

The current model applies `-wT*T + wP*P - wN*N - wS*C` to perceived next targets, including row ends and foyer-entry doors. Admission paths provide remembered target locations for wayfinding only; they give no utility bonus. Peer share uses observed intended direction, including stationary people with a target. Norm perception includes stationary queue cutting and opposing motion. Current-target identity makes switching cost local to each decision stage. Every stage reconsiders at `decisionInterval`; all behavioral observations are frozen at tick start. The separate population-wide crowd reward has been removed in local mode.

The default `arrival` world object reconstructs an admission path from `M2` to each occupied seat. These paths are labeled reconstructed and are not measured historical arrivals or a simulated admission crowd. Supply actual portal sequences using `arrival.routesBySeat` to use recorded ingress instead. Optional `geometry.visibilityWalls` segments add observation occlusion; these do not create new body-collision geometry. Existing barrier, corridor-wall, and foyer-wall openings also affect sight. Visible targets and previously remembered targets are distinguished in the decision record.

Perceived time estimates travel to the next target and, when enabled, delay from observed waiting people ahead. A stopped unit facing observed opposing traffic in the same narrow seat row also estimates future delay from its experienced wait, scaled by `rowBlockWaitFactor`. This allows utility-based reconsideration while preserving fixed preferences and body constraints. Queue and norm rules are explicit assumptions rather than fitted observations.

For the behavioral component alone, run `python run.py --settings behavioral_only_settings.json`. See [BEHAVIOR_CHANGES.md](BEHAVIOR_CHANGES.md) for the complete change list, settings, admission-route schema, observation rules, and limitations.

Choosing a longer path can still be a utility result: peer influence, perceived norm violation, and target-switching costs can outweigh the time saving from a nearby door. The default reconstructed admission path retains M2 as a known target, but M2 receives no familiarity reward. Inspect `lastDecision.alternatives` to distinguish a higher-utility distant target from a nearby target omitted by perception or a movement problem after a nearby target was selected. `timeScale` controls the relative strength of time: decreasing it increases the time penalty while preserving the unit-mean weight distribution. `weightSigma` controls preference extremes. These are separate modeling choices; no tuning changes were applied during this implementation.

### Supplied social-force equations

The current two-plan model now explicitly integrates `dv/dt = f_des + f_obs + f_int`. `bailey_motion/social_force.py` implements desired-velocity relaxation, exponential obstacle repulsion, and the supplied relative-velocity / signed-angle interpersonal force. `plans.obstacle_contacts()` supplies schematic wall, aisle, and barrier samples. Each person's optional `params.comfortDistance` overrides the global comfort-distance default. No extra trait is sampled by default.

Click a unit and inspect `data.socialForce` to see its latest desired, obstacle, interaction, and total acceleration. The record also distinguishes raw Euler velocity, velocity after caps, and the request after optional local steering. Evaluation time and position are recorded because engine constraints and subsequent transfers can change actual motion. Full JSON exports include these records; the CSV format is unchanged.

To disable the previous sidestepping search while using the manuscript forces, run:

```powershell
python run.py --settings force_only_settings.json --population 300 --max-seconds 180
```

Hard constraints, velocity caps, row projection, engine movement fallbacks, and timed staircase transfers remain active. Interpersonal force uses the finite `interactionRange` neighborhood. Obstacle surfaces remain schematic, without individual seat-back or door-jamb contacts. See [SOCIAL_FORCE_CHANGES.md](SOCIAL_FORCE_CHANGES.md) for every code/behavior change, the equation-to-code mapping, individual comfort-distance configuration, and comparison instructions.

### Change geometry, population traits, or engine limits

In the desktop **World JSON** tab, edit the full world and click **Apply world + reset**. For reusable terminal experiments, copy `bailey_motion/default_world.json` to `results/world-example.json`, edit that copy, then run:

```powershell
python run.py --config results/world-example.json --population 100 --ticks 1000
```

A world file must contain the full configuration, including `geometry`, `distributions`, and `limits`. Unlike policy-settings overrides, it is not merged with the default world. Explicit CLI population, seed, dt, and maximum-time options override the loaded values.

The current layout's regions, source portals, and destination entrances are declared together in JSON. Keep their dimensions and links consistent when editing; major footprint changes can still require changing the schematic row construction and viewer. Legacy mode retains the older hard-coded offsets. This is the Bailey configuration format; the older square-room `shared/building-example.json` is not compatible.

### Change routing, utility, or steering code

Edit `bailey_motion/user_model.py` in your IDE for permanent bundled-policy changes, or edit the full module in the desktop **Python policy** tab and click **Apply code + reset**. To keep an in-window edit, use **Save policy** with a new filename such as `results/my_policy.py`.

```powershell
python run.py --policy results/my_policy.py --settings results/weights-example.json --ticks 1000
```

Useful methods to locate:

| Method | Change here to alter |
|---|---|
| `sample_weights()` | The joint preference distribution |
| `setup()`, `arrival.py` | Fixed weights and explicit admission-route memory |
| `behavior.LocalBehavior.features()`, `behavioral_utility()` | Observable action features and the signed behavioral dot product |
| `behavior.LocalBehavior.available_actions()`, `perceived_actions()` | Next physical targets and perception/memory filtering |
| `perception.visible()`, `line_of_sight()` | Range, viewing angle, and schematic wall occlusion |
| `choose()`, `behavior.LocalBehavior.choose()` | Utility components and target scoring; legacy code stays in `user_model.py` |
| `goal()` | Waypoint placement along rows, aisles, and circulation tracks |
| `compute_velocity()` | Desired motion, acceleration integration, and speed limits |
| `force_components()`, `social_force.py` | The supplied desired, obstacle, and interpersonal acceleration equations |
| `navigation.steer()` in `navigation.py` | Local, collision-checked sidestepping without changing a selected exit |
| `decide()`, `after_move()` | Decision timing and transitions between stages |

Source-tab **Restore source** changes the editor buffer only; click Apply to execute it. **Restore world** and **Restore settings** reset the experiment immediately. In-window edits are not automatically written back to package files. Applying settings uses the currently applied source, not any unapplied source-buffer edits.

Applying a policy executes trusted Python normally. Use source code you intend to run. The API and custom-policy contract are described below.

## How to run comparison experiments

Keep world geometry, dt, population, and stopping rule fixed while changing one behavioral assumption. Try multiple seeds so one sampled population does not determine the conclusion. A simple PowerShell series is:

```powershell
foreach ($experimentSeed in @(11, 12, 13)) {
    python run.py --population 30 --seed $experimentSeed --max-seconds 120 --output "results/baseline-seed-$experimentSeed.json" --csv "results/baseline-seed-$experimentSeed.csv" --include-weights
}
```

Choose another filename prefix for the next condition or repeated runs. Compare remaining participants as well as exit-time means: a lower mean among exited people can coexist with more people stuck inside. If you disable collisions, regions, or door capacity to diagnose a mechanism, label that condition explicitly.

These experiments simulate consequences of assumed preferences and motion rules. The code does not estimate weights from observed evacuation data or fit distribution parameters automatically.

## Command reference

```powershell
python run.py --help
python run.py --config bailey_motion/default_world.json --settings bailey_motion/default_policy_settings.json --ticks 200
python run.py --disable-portal AUD4 --disable-portal SIDE_E1 --ticks 1000
python run.py --no-collisions --no-regions --no-door-capacity --ticks 100
```

`--n` aliases `--population`; `--animate` aliases `--gui`. Repeat `--disable-portal` for multiple IDs. Omit `--output` and `--csv` to print the summary without creating result files. The full default-world and default-policy JSON files are in `bailey_motion/`.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `python` is unavailable or its Windows launcher fails | Use the local runtime command above, or a working Python 3.10+ interpreter |
| A relative-import error when running `app.py` | Launch `run.py --gui` from the port directory instead |
| Tcl/Tk cannot initialize | Run headless by omitting `--gui`; for graphics, use a regular Python installation with working Tcl/Tk in a desktop session. `python -m tkinter` is a separate installation check |
| Window opens but nobody moves | Click Run; also allow for sampled reaction delays or inspect using One tick |
| Form changes appear to have no effect | Click Reset / apply controls; editor changes need their own Apply button |
| GUI reports a policy/configuration error | Open Inspector / errors for the traceback; correct the edit or restore defaults |
| Output already exists | Choose a new filename; exports intentionally do not overwrite prior experiments |
| Output parent directory does not exist | Save in the supplied `results/` folder or create your desired subdirectory first |
| People remain at the time limit | Inspect remaining regions and individual state; persistent blocking is a retained source behavior, not necessarily an installation problem |
| Python and JavaScript long runs differ | See the floating-point reproducibility limits below; matched seeds do not guarantee identical dense long-run trajectories across runtimes |

To check the implementation from this directory:

```powershell
python -m unittest discover -s tests -v
```

The graphical control test skips if Tk cannot initialize; the other tests run headless.

## File correspondence

| JavaScript source | Python port | Role |
|---|---|---|
| `src/config.js` | `bailey_motion/config.py`, `default_world.json` | World defaults and input validation |
| Settings in `src/user-model.js` | `bailey_motion/default_policy_settings.json` | Utility and motion coefficients |
| `src/random.js` | `bailey_motion/random.py` | Same seeded uniform, cached Gaussian, gamma, beta, lognormal, shuffle, and clipping |
| `src/geometry.js` | `bailey_motion/geometry.py` | Exact seat allocation, curved regions, portals, geometric queries |
| New specification-based geometry | `bailey_motion/plans.py`, `default_world.json` | Two plans, six-access barrier, named entrance topology, threshold intersections |
| New connection service | `bailey_motion/transfers.py` | Checked landings, two-flight/two-lane transfers, identity-preserving arrivals, final threshold events |
| Local behavioral specification | `bailey_motion/behavior.py` | Physical local actions, frozen observations, four utility features, reconsideration, and decision diagnostics |
| Admission memory | `bailey_motion/arrival.py` | Recorded or explicitly reconstructed entrance-to-seat paths |
| Observation geometry | `bailey_motion/perception.py` | Visibility range/angle, wall occlusion, and apertures |
| Local steering correction | `bailey_motion/navigation.py` | Predictive body avoidance and legal passing velocities, retaining each selected target |
| Supplied Social Force Component | `bailey_motion/social_force.py` | Explicit acceleration terms, their sum, and Euler integration |
| `src/engine.js` | `bailey_motion/engine.py` | Clock, sequential motion, body collisions, landing search, stair service, callbacks, telemetry |
| `src/user-model.js` | `bailey_motion/user_model.py` | Full v2 utility, correlated weights, routing, shocks, steering, and transitions |
| `src/viewer.js` | `bailey_motion/viewer.py` | Read-only rendering of both floors, seats, routes, portals, and agents |
| New plan rendering | `bailey_motion/plan_viewer.py` | Barrier gaps, entrance markers, stair lanes, excluded elevator, and exterior threshold lines |
| `src/app.js`, HTML controls | `bailey_motion/app.py` | Native desktop controls, editors, inspection, door toggles, and exports |
| Browser source compilation | `bailey_motion/loader.py` | Trusted editable Python-policy compilation |
| — | `run.py`, `bailey_motion/cli.py`, `__main__.py` | Headless command line / desktop entry points |
| — | `tests/` | Reference comparisons, mechanics/policy checks, and optional desktop smoke test |

`records.py` supplies dictionaries with attribute access so the original camelCase agent/world fields remain recognizable. The policy uses Python method names such as `before_tick` and `after_move`; the engine also accepts source-style optional hook names. The API offers both `set_region`/`use_portal` and `setRegion`/`usePortal`.

## Desktop controls

`--gui` opens a native window with the ground and balcony maps. It starts paused. Run/Pause, one tick, ten ticks, population/seed/dt reset, playback speed, physical constraint switches, per-portal enable switches, and clickable individual inspection correspond to the browser controls.

The editor tabs contain full Python policy source, world JSON, policy settings JSON, and inspector/errors. Apply buttons reset the world with the edited code/settings. Restore buttons recover bundled defaults. File export buttons save policy source, settings, world, source-format CSV, expanded CSV, or a full run. Save to a new filename under this port's directory.

Applying a policy executes trusted Python code with normal process access. The editor is not a security sandbox. Python source replaces the browser's JavaScript source language; it is not a JavaScript interpreter. The native viewer uses the same coordinates and map conventions, with Tk drawing primitives rather than HTML/CSS styling.

## Configuration and policy API

The default JSON world extends the port with the two-plan specification above. It retains proportional seat allocation and the joint utility-weight model. The original source world is archived in `bailey_motion/legacy_world.json`, and the old source-parity tests explicitly use that archive. Neither world uses the square-room `shared/building-example.json` format.

```powershell
python run.py --config bailey_motion/default_world.json --settings bailey_motion/default_policy_settings.json --ticks 200
python run.py --disable-portal AUD4 --disable-portal SIDE_E1 --ticks 1000
python run.py --no-collisions --no-regions --no-door-capacity --ticks 100
python run.py --policy my_policy.py --ticks 100
```

A policy must define `create_policy(settings=None)` (or `UserModel`) returning an object/dictionary with `decide(agent, api)`. Other hooks are optional. Example:

```python
def create_policy(settings=None):
    return {"decide": lambda agent, api: {"vx": 0.0, "vy": 0.0}}
```

API properties: `api.t`, `dt`, `tick`, `config`, `geometry`, `agents`, `portals`, `current`. Methods: `random()`, `normal()`, `sample(spec)`, `point(r, angle)`, `polar(agent)`, `radius(agent)`, `distance(a, b)`, `neighbors(agent, range)`, `clear(agent, x, y, region)`, `set_region(...)`, `portal(id)`, `use_portal(agent, id)`, `exit(agent, id)`, `log(message)`.

For Python scripts/notebooks with this directory on the import path:

```python
from bailey_motion import BaileyEngine, UserModel, default_config

world = default_config()
world.population = 100
engine = BaileyEngine(world, UserModel({"weightSigma": 1.2, "weightRho": -0.15}))
engine.run_steps(1000)
print(engine.summary())
```

## Legacy fidelity and retained limitations

### Edge-cluster and waypoint corrections

The current two-plan model corrects three numerical/steering artifacts found in edge clusters:

- Doorway alignment uses the opening width and body radius rather than a fixed angular tolerance. Units align before turning outward through a narrow door.
- Circulation waypoints retain each person's legal radius instead of pulling all opposing flows onto one centerline. Orchestra aisle waypoints center bodies before the narrow loge access openings.
- Radial-only correction waypoints exceed the velocity policy's 0.025 m arrival tolerance, avoiding a permanent stop just short of the next angular waypoint.

When a requested motion predicts a collision or physical progress stalls, `navigation.py` considers nearby legal velocities. A deterministic encounter-level passing-side tie break resolves head-on symmetry. This adds no random draws, does not resample preferences or assign another exit, and never bypasses the hard body, wall, transfer, or final-threshold checks. Seat-row motion remains constrained to the row. Genuine doorway-capacity and blocked-landing queues can still wait normally.

New regression tests reproduce isolated wall-edge stalls, a narrow access approach, the sub-arrival dead zone, and a head-on pair. With seed 2026, the corrected 30-person case clears in approximately 53.5 simulated seconds and the 300-person case in approximately 73.9 seconds; the preceding steering version left 97 of 300 people inside at 120 seconds. These are diagnostic simulation outcomes, not calibrated evacuation-time estimates. Saved outputs are `results/navigation-fix-300.json` and `.csv`.

After code changes, restart `python run.py --gui` to load the updated modules and bundled policy. An already-open window or an older saved `--policy` file may still be using old source. Set `localAvoidance` to `false` for controlled comparisons of the added steering; the waypoint geometry corrections still apply.

The archived original layout is available for source-port replay:

```powershell
python run.py --config bailey_motion/legacy_world.json --population 300 --ticks 1000
```

The current default includes geometry, force, and local-behavior revisions and is no longer expected to reproduce JavaScript trajectories. These modeling limitations remain:

- Admission routes are reconstructed unless recorded routes are supplied. They affect remembered target availability but never add a familiarity utility bonus.
- Visibility uses schematic walls and optional segments, without eye height, body occlusion, or individual seat backs. Remembered targets can remain available outside current sight.
- Behavioral observations are frozen each tick; social forces and actual moves remain sequential. Queue-cutting and wait-time estimates are operational assumptions, not calibrated measurements.
- The archived layout retains legacy geometry, forces, nearest-aisle selection, and global crowd counts, with the current four-factor utility; `behaviorMode: "legacy"` is available for comparisons on current geometry. Current local mode uses utility in every decision stage and no global crowd reward.
- Interior door crossings use named, checked landing transfers; stairs use separated timed lane queues. Final exits use swept first-floor threshold intersections.
- Geometry and force scales are provisional. Existing steering and collision rules can still generate persistent opposing-flow blockages; incomplete runs retain null clearance times.
- Source CSV omits utility weights; the optional expanded CSV and full JSON make them available without changing the simulation.
- UI errors/CLI validation add clear reporting without calibrating the model. The local-steering correction addresses the identified edge/centerline stalls; it does not remove genuine capacity or blocked-landing queues.

For the legacy layout, Python and JavaScript use different transcendental implementations and can differ by tiny floating-point amounts. Archived seeded initialization, distribution draws, sparse trajectories, and early dense checkpoints are compared against JavaScript. Contact constraints and discrete choices can amplify differences in dense long runs. The earlier legacy sample of 259 Python exits versus 256 JavaScript exits at 1,000 ticks is retained in the saved historical results; it does not describe the new two-plan world.

## Verification

Run `python -m unittest discover -s tests -v`. Checks cover complete JavaScript-reference agent state (12 agents through 1,000 ticks, 30 through 100, and 300 through 10), random draw order, distributions, exact seating capacities, covariance/mean, noise caching, reaction delay, collisions, row projection, door tokens, stair transfers, closure discovery, callbacks, exports, input bounds, editable Python source, and read-only drawing. `test_app.py` uses actual Tk controls and skips when a graphical runtime cannot initialize.

The archived port's earlier verification is retained in `results/verification.json`. For the current two-plan revision, all 38 headless tests passed (21 archived-port regression checks and 17 new plan/transfer checks), and the actual Tk desktop test passed in a hidden window outside the sandbox. It also checks the 34 portal controls and disabled elevator. The sandbox itself cannot initialize Tk's native file access. `results/two-plan-verification.json` records the current checks and sample summary. Historical `results/bailey-300-1000ticks.json` and `.csv` belong to the earlier layout.

The reference fixture is generated from the sibling JavaScript source. `tests/source_manifest.json` records the corresponding normalized source hashes so changes to the reference implementation are visible.

`tests/test_plans.py` separately checks the new specified topology, exact inventories, physical barrier openings, connector widths, independent plans, all six access transfers, flight/lane ordering, blocked landings, first-floor stage arrivals, all eleven threshold crossings, sub-tick exit time, elevator exclusion, and end-to-end identity/population conservation. New sample outputs are `results/two-plan-300-1200ticks.json` and `.csv`; the crowded run is intentionally reported as unfinished where steering blockages remain.

The later steering-correction verification adds `tests/test_navigation.py`: eight cases for edge alignment, head-on passing without overlap or target reassignment, the arrival-tolerance dead zone, narrow access centering, disabled thresholds, settings validation, reproducibility of sampling, and the formerly stuck 30-person run. All 46 headless tests passed, as did the actual desktop control test in a hidden Tk window. Two 300-person runs (seeds 2026 and 7) fully cleared in approximately 73.9 and 56.0 simulated seconds. The seed-2026 behavioral weights and radii match the pre-correction run, and every completed participant has a first-floor threshold-crossing event. `results/navigation-verification.json` records these checks. The earlier `two-plan-*` outputs retain the pre-correction baseline for comparison.

For the subsequent supplied-force implementation, all 61 headless tests and the actual hidden-window Tk desktop test passed (62 total). `tests/test_social_force.py` adds 15 equation and integration cases. The two 300-person manuscript-force runs clear in approximately 63.6 seconds (seed 2026) and 73.3 seconds (seed 7), retaining their respective baseline sampled traits and utility weights. Force sums, raw Euler diagnostics, and all first-floor crossing records were checked in the exported JSON. A separate 30-person run with local avoidance disabled clears in approximately 44.8 seconds. These are diagnostic simulation results rather than calibrated evacuation-time estimates. Outputs and checks are recorded in `results/social-force-verification.json`, with run files named `social-force-300-seed2026`, `social-force-300-seed7`, and `social-force-only-30`.

For the local behavioral revision, all 88 headless tests and the actual hidden-window Tk desktop test passed (89 total). The 27 new behavioral tests include all six manuscript examples, recorded/reconstructed admission memory, viewing angle/range/wall occlusion, directional peers, stationary queue cutting, queue/row wait estimates, decisions at one- and three-second intervals in every region, fixed weights, utility-based row/F choices, MAIN correctness, and safe late door changes. Verified 300-person runs with the retained 3-second interval fully clear in approximately 67.6 seconds (seed 2026) and 70.6 seconds (seed 7). Exported utilities, their argmax, unchanged sampled traits/weights, and all 600 first-floor threshold events were checked. `results/local-behavior-verification.json` records the checks; `local-behavior-verified-*` files contain the final-version outputs. Earlier `local-behavior-*` probes are retained as diagnostic baselines rather than current results.

The familiarity-removal revision uses four behavioral weights and the latent-correlation bound -1/3 < rho < 1. Historical JavaScript trajectory comparisons use `tests/archived_five_weight_policy.py`, a frozen test-only fixture that the simulator never selects. Existing older result files and change logs describe their recorded five-weight versions, not the current utility. The focused removal tests use exactly 300 units per engine.
