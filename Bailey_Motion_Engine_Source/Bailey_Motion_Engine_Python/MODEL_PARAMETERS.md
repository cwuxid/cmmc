# Model parameter reference

This reference describes the Python implementation and its bundled configuration. Defaults below come from `bailey_motion/default_world.json`, `bailey_motion/default_policy_settings.json`, and the optional guidance modules. Distances are schematic metres, times are simulated seconds, and speeds are metres per second. Geometry reproduces the supplied topology; its dimensions are approximations, not a surveyed building model. This document contains no experimental results.

World settings belong in the world JSON. Behavioral and force settings belong in the policy-settings JSON. `studentMode`, `crowdManagers`, and `ledStrips` are optional world settings. A custom trusted Python policy can implement different semantics from those described here.

## Run, audience, and numerical controls

| Parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `seed` | 2026 | integer | Reproducibility seed. Public input accepts unsigned 32-bit values. The underlying generator maps zero to one. Repeat the full configuration, policy, time step, and random-stream mode when comparing runs. |
| `population` | 300 | people | Number of occupied seats sampled from the 1,329-seat inventory. Public validation accepts 1 through 1329; direct engine construction also clamps to inventory capacity. Staff do not count toward this number. |
| `dt` | 0.1 | seconds/tick | Integration and event time step. Public validation requires 0 < dt <= 0.4. Changing it changes numerical motion, collision resolution, and event timing. The 0.4 ceiling is an input guard, not evidence of calibrated numerical accuracy. |
| `playback` | 10 | simulated seconds/wall second | GUI playback rate. It controls how quickly ticks are presented, without changing the simulated integration step or intended physical speeds. |
| `limits.maxSeconds` | 1800 | seconds | Simulation horizon. An incomplete run is stopped at the first tick reaching the cap; incomplete clearance must not be reported as a completed evacuation time. |
| `limits.hardCollisions` | true | boolean | Reject overlapping body motions. Disabling it retains soft social-force interactions. |
| `limits.enforceRegions` | true | boolean | Reject proposed positions outside the current permitted region. Portal eligibility and transitions remain separate rules. |
| `limits.doorCapacity` | true | boolean | Apply door token throughput limits. Disabling it does not remove connector lane spacing, occupancy limits, aperture fit, or landing clearance. |
| `studentMode` | false; optional | boolean | Give every audience member complete layout knowledge and shortest-distance route choice. Reaction delay, bodies, movement forces, queues, and connector timing remain active. Students suppress crowd-manager guidance, manager bodies, and LED guidance. |

The GUI must successfully reset before an edited run setting becomes the engine's setting. A rejected value such as dt = 2 does not establish a two-second integration run. Compare the active run configuration, rather than only the text remaining in an input box.

## Arrival memory and individual sampling

| Parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `arrival.defaultEntrance` | M2 | exterior portal ID | Reconstruct a plausible admission route in reverse, from this entrance to each seat. This initializes remembered paths; it is not a familiarity utility coefficient. |
| `arrival.routesBySeat` | empty object | seat-label map | Optional explicit admission memories. Each seat entry supplies a connected `portals` list, exterior first, and may supply `rowSide`. The route must reach the seat's section. |
| `arrival.routesBySeat.<seat>.portals` | inferred | list of IDs | Admission-route portal sequence, used to initialize path knowledge. |
| `arrival.routesBySeat.<seat>.rowSide` | inferred | ROW_LEFT / ROW_RIGHT | Initial row-side convention from admission. |
| `distributions.<trait>.type` | varies | normal / beta / lognormal | Distribution used at initialization. Traits below are sampled once per person. |
| `distributions.<trait>.mean` | varies | trait units | Requested arithmetic mean, including for lognormal sampling. |
| `distributions.<trait>.sd` | varies | trait units | Standard deviation, not variance. A value below 1e-10 returns the mean before clipping and consumes no sampling draw. |
| `distributions.<trait>.min`, `.max` | optional | trait units | Clip the sampled value to these limits. This is clipping, not rejection sampling from a truncated distribution. |

| Distribution | Default | Units/type | Actual use |
| --- | --- | --- | --- |
| `sanity` | beta; mean 0.75, sd 0.16 | dimensionless | Supplies the clipped `betaDistance` exponent in the extra distance term of ordinary local utility. This is separate from the time weight. |
| `groupthink` | beta; mean 0.55, sd 0.20 | dimensionless | Supplies `betaCrowd`, clipped from twice the draw minus one. Used by legacy behavioral route choice, not the current local peer weight. |
| `pack` | beta; mean 0.45, sd 0.22 | dimensionless | Sampled and exported, but unused by the bundled decisions and forces. |
| `norms` | beta; mean 0.65, sd 0.17 | dimensionless | Scales interaction amplitude in legacy social forces. It does not determine the current behavioral norm weight, and is not used by manuscript interaction forces. |
| `speed` | normal; mean 1.29, sd 0.19; min 0.5, max 2.3 | m/s | Individual desired speed; affects physical driving, speed limits, perceived travel time, and connector travel. |
| `reaction` | lognormal; mean 2, sd 1.2; min 0, max 40 | seconds | Delay before the person's initial evacuation movement. Students also retain this delay. |
| `radius` | normal; mean 0.2025, sd 0 | metres | Body radius, aperture fit, body exclusion, and connector spacing. Default bodies have identical radii. |
| `panic` | absent; policy fallback | dimensionless | Optional per-person panic sensitivity, clipped into [0,1]. If absent, `panicMean` and `panicSD` supply the fallback distribution. |
| `comfortDistance` | absent; policy fallback | metres | Optional positive per-person override for manuscript obstacle-force decay distance. |

For a lognormal with arithmetic mean m and standard deviation s, the implementation uses latent variance log(1 + s squared / m squared) and latent mean log(m) minus half that variance. Beta sampling converts the requested moments to shape parameters, but floors its concentration and shapes; extreme requested moments need not be reproduced exactly. Changing even an unused sampled trait can change later random draws in the ordinary sequential stream.

## Behavioral utility and all policy settings

Each person receives four fixed, strictly positive weights in the order time T, peers P, norms N, switching S. There is no familiarity weight. The local feature vector is (-T, P, -N, -C), with travel time normalized by `timeScale`. The behavioral dot product is -wT*T + wP*P - wN*N - wS*C. Ordinary local utility additionally includes the distance score and held panic/residual shocks; optional guidance adds utility bonuses. `behavioralOnly` removes the extra distance and shock terms in local mode.

The four-dimensional weight vector is joint lognormal: draw a normal vector with covariance sigma squared times [(1-rho) I + rho 11-transpose], and mean -sigma squared/2 in every component, then exponentiate componentwise. Thus every component has population mean one. Vectors are not divided by their sum. `weightRho` describes latent-normal correlation, not the correlation of exponentiated weights.

| Parameter | Default | Units/type | Meaning and applicability |
| --- | --- | --- | --- |
| `weightSigma` | 1 | dimensionless | Latent-normal standard deviation. Larger values produce greater heterogeneity and heavier positive weight tails. Must be positive. |
| `weightRho` | -0.15 | dimensionless | Common latent correlation. For four weights the positive-definite range is -1/3 < rho < 1. Negative values probabilistically associate strong sensitivity to one feature with weaker sensitivities to others. |
| `timeScale` | 1 | seconds | Normalize perceived local travel time, including enabled queue and row-block estimates. Larger values weaken the time penalty relative to the other utility components; physical speed is unchanged. |
| `decisionInterval` | 3 | seconds | Periodic decisions in current two-plan geometry. Stage transitions and newly learned closures can trigger earlier reconsideration. This is separate from force integration dt. |
| `noiseInterval` | 15 | seconds | Hold decision shocks in time buckets of this length. Shocks are indexed by person, option, and kind within a bucket. |
| `shockSD` | 0.2 | utility units | Standard deviation of panic and residual normal shocks. Local `behavioralOnly` disables these terms. |
| `panicMean` | 0.45 | dimensionless | Fallback mean for a person's panic sensitivity if no `panic` distribution is supplied. |
| `panicSD` | 0.2 | dimensionless | Fallback standard deviation for panic sensitivity. The panic envelope is sensitivity times (1 - exp(-t/60)); it scales a utility shock, not desired speed. |
| `observeRadius` | 4 | metres | Neighborhood for local peer, queue, and counterflow observations. Neighbor queries use this radius in place of general target `visionRange`. |
| `discoveryRadius` | 2.2 | metres | Distance for learning a nearby disabled portal, subject to visibility. Managers have their own information rules and delayed notifications. |
| `visionRange` | 12 | metres | General action-target visibility distance. Remembered or instructed actions can remain available beyond direct sight. Student routing bypasses this knowledge restriction. |
| `fieldOfViewDegrees` | 360 | degrees | Angular visibility cone. A smaller value uses motion direction, or stored heading when stationary. Manager communication has its own omnidirectional range and line-of-sight test. |
| `peerDirectionToleranceDegrees` | 45 | degrees | Alignment tolerance for counting neighbors as choosing an action's direction. |
| `queueObservationDistance` | 3 | metres | Distance around a target within which committed slow people can be perceived as a queue. |
| `queueSpeedThreshold` | 0.25 | m/s | Speed threshold in local queue estimates. It differs from the moving-person threshold used by norm observations. |
| `rowBlockWaitFactor` | 1 | multiplier | Scale the perceived extra wait from observed opposing row blockage. The estimate uses accumulated blockage plus one decision interval. Zero removes this contribution. |
| `perceivedQueueDelay` | true | boolean | Include observed queue and row-block delays in perceived time. Does not remove physical queues or norm observations. |
| `behavioralOnly` | false | boolean | In local mode retain the four-weight utility and guidance, while dropping the extra distance and panic/residual terms. Legacy choice does not use this switch. Students bypass utility maximization. |
| `behaviorMode` | local | local / legacy | Select current perceived next-target decisions or the retained legacy route-choice procedure. Students and optional guidance require current geometry with local behavior. |
| `legacyDecisionInterval` | 1.5 | seconds | Decision interval for archived geometry. Current two-plan geometry uses `decisionInterval` even when `behaviorMode` is legacy. |
| `relaxationTime` | 0.65 | seconds | Desired-velocity relaxation time in acceleration (desired velocity minus current velocity)/tau. Smaller values drive faster velocity adjustment. |
| `obstacleStrength` | 0.8 | acceleration scale | Manuscript obstacle repulsion magnitude. Hard region and body constraints are independent of this soft force. |
| `comfortDistance` | 0.15 | metres | Default manuscript obstacle exponential decay distance, unless overridden per person. |
| `interactionStrength` | 0.4 | model scale | Legacy social-force interaction multiplier only. Not used by the manuscript interaction formula. |
| `interactionRange` | 2.6 | metres | Neighbor cutoff for physical interactions and the neighbors passed to local avoidance. This is separate from behavioral observation range. |
| `interactionLambda` | 0.25 | model coefficient | Relative-velocity contribution to the manuscript interaction direction. Changing it changes anticipatory interaction geometry. |
| `interactionN` | 1 | dimensionless | Angular attenuation shape of the lateral manuscript interaction term. |
| `interactionNPrime` | 1 | dimensionless | Angular attenuation shape of the longitudinal manuscript interaction term. |
| `maxSpeedFactor` | 1.35 | multiplier | Cap speed relative to the person's desired speed, alongside waypoint and per-tick displacement limits. |
| `localAvoidance` | true | boolean | Enable predictive local velocity steering outside seat rows. Turning it off retains other physical constraints and forces. |
| `avoidanceLookahead` | 0.65 | seconds | Closest-approach horizon for predictive steering. |
| `passingClearance` | 0.04 | metres | Additional predictive separation padding, reduced near contact. |
| `progressTimeout` | 2 | seconds | Time without sufficient anchored displacement before a person is considered stalled for steering. It does not teleport a person or prescribe a new destination. |
| `socialForceMode` | manuscript | manuscript / legacy | Select supplied desired, obstacle, and interaction force forms or retained legacy forces. Archived geometry uses legacy forces regardless. |

An additional optional policy key is `pairedRandomness` (default false). When true, shocks use counter-keyed draws from seed, person, time bucket, kind, and choice, which prevents a different decision-option ordering from consuming a different shared RNG sequence. Optimization uses paired randomness; ordinary GUI runs retain the default unless overridden. It does not make all model configurations physically equivalent.

## Geometry: coordinates, seats, and boundaries

The polar construction is x = r cos(theta), y = centerY + r sin(theta). Most geometry angle lists and angular bounds store fractions of pi. Explicit portal `angle` and entrance `aisleAngle` are already radians. This difference matters when editing JSON. Floor 0 is the first floor; floor 1 is the balcony. A transfer moves a person to a named landing on the other plan; two people on different floors do not collide merely because their drawn coordinates coincide.

| Parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `geometry.layoutVersion` | 2 | integer | Select current explicit two-plan geometry when at least 2. Older geometry uses archived construction and behavior paths. |
| `geometry.centerY` | 7.5 | metres | Common y coordinate of the semicircular seating center. Explicit portal and entrance coordinates must be updated consistently after geometric changes. |
| `geometry.aisleHalfWidth` | 1.3 | metres | Half-width of radial aisles, giving a nominal 2.6 m full width. Row construction reserves aisle space at block ends. |
| `geometry.aisleAngles` | [0.025, 0.215, 0.405, 0.595, 0.785, 0.975] | fractions of pi | Six radial aisle directions. Seat construction also uses fixed outside angular bounds of 0.02 and 0.98 times pi. |
| `geometry.plans[].id` | main; balcony | IDs | Plan identifiers used by portals and entrances. |
| `geometry.plans[].floor` | 0; 1 | integer | Floor associated with each plan. |
| `geometry.plans[].name` | descriptive labels | text | Display name of each plan. |
| `geometry.geometryStatus` | topology known; metric dimensions approximate | text | Documentation metadata; does not change movement. |
| `geometry.completionRule` | first_floor_exterior_threshold | text | Descriptive/export metadata for the implemented first-floor threshold completion rule. Editing this string alone does not create a different completion algorithm. |
| `geometry.unitTreatment` | equal units; identical radius; no wheelchair class | text | Descriptive metadata. Body properties come from distributions; this text does not create mobility classes. |

| Section | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| orchestra | floor 0; capacity 527; firstR 6.7; step 0.64; rows 16; pitch 0.58 | metres where dimensional | Orchestra seat inventory. |
| loge | floor 0; capacity 486; firstR 17.5; step 0.68; rows 7; pitch 0.60 | metres where dimensional | Elevated mezzanine/loge on the first plan. |
| balcony | floor 1; capacity 316; firstR 16; step 0.68; rows 9; pitch 0.67 | metres where dimensional | Second-plan seat inventory. |

Each `geometry.sections[]` has `id`, `floor`, `capacity`, `firstR`, `step`, `rows`, and `pitch`. `firstR` is the first row radius, `step` the radial row increment, and `pitch` the nominal seat spacing used to assess row-block capacity. Seats are allocated to blocks by a largest-remainder procedure and then placed evenly; actual individual spacing need not equal pitch exactly. Current validation preserves the specified section capacities, totaling 1329. Seats are generated from these specifications, rather than individually traced from the seating drawings.

| Parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `geometry.orchestraBarrier.radius` | 16.9 | metres | Orchestra/loge barrier radial position. |
| `geometry.orchestraBarrier.width` | 0.35 | metres | Barrier thickness, used in physical and visibility geometry. |
| `geometry.orchestraBarrier.accessWidth` | 1.3 | metres | Width of the six barrier gaps. Keep explicit ACCESS portal widths consistent. |
| `geometry.orchestraBarrier.accessAngles` | same six fractions as aisleAngles | fractions of pi | Gap directions. |
| `geometry.orchestraBarrier.accessLength` | 1.5 | metres | Retained metadata. Current connector travel uses each ACCESS portal's `length` and `flights`. |
| `geometry.zones.<zone>.floor` | orchestra/loge 0; balcony 1 | integer | Seating-zone floor. |
| `geometry.zones.<zone>.minR`, `.maxR` | see zone table | metres | Radial bounds of seating and radial aisle movement. |
| `geometry.zones.<zone>.outerRegion` | access / rim / balcony-rim | region ID | Named continuation from that seating zone. |

| Zone | Default | Units/type | Continuation |
| --- | --- | --- | --- |
| orchestra | minR 6.3; maxR 16.525 | metres | access |
| loge | minR 17.3; maxR 22.2 | metres | rim |
| balcony | minR 15.7; maxR 22.75 | metres | balcony-rim |

Each `geometry.regions.<id>` has `floor` and `kind`. Annuli have `minR`, `maxR`, `trackR`, `minAngle`, and `maxAngle`; rectangles have `minX`, `maxX`, `minY`, and `maxY`. Angular bounds are fractions of pi. Rectangle position bounds are inset for body radius. Annular radial bounds are permitted center positions and are not uniformly eroded by body radius. `trackR` is used by explicit legacy behavioral arc-distance estimates; current local goals and shortest-route geometry do not force pedestrians to that radius.

| Region | Default | Units/type | Use |
| --- | --- | --- | --- |
| rim | floor 0; r 22.02 to 24.05; trackR 23.15; angle 0.012 to 0.988 | metres; fractions of pi | First-floor circulation outside loge. |
| corridor | floor 0; r 24 to 27.3; trackR 25.5; angle 0.005 to 0.995 | metres; fractions of pi | Semicircular corridor beyond auditorium doors. |
| balcony-rim | floor 1; r 22.57 to 24.5; trackR 23.15; angle 0.008 to 0.992 | metres; fractions of pi | Balcony circulation. |
| foyer | floor 0; x -12.4 to 12.4; y 32.2 to 41.2 | metres | Main first-floor exit hall. |
| stage-east | floor 0; x 21.5 to 24.25; y 3.8 to 6.8 | metres | Landing region for east stage-side stairs. |
| stage-west | floor 0; x -24.25 to -21.5; y 3.8 to 6.8 | metres | Landing region for west stage-side stairs. |

`geometry.visibilityWalls` defaults to an empty list. Each additional segment supplies `floor`, `start: {x,y}`, and `end: {x,y}` with finite, distinct endpoints. These segments obstruct observations, not physical movement. Built-in visibility boundaries include the first-floor orchestra barrier, corridor inner wall, and foyer walls. People and individual seat backs are not visibility occluders. To add a physical wall, changing this list alone is insufficient.

## Portals and transfer entrances

The authoritative current map is `geometry.portals` plus `geometry.entrances`. Coordinates below remain explicit in `default_world.json`; the schema and family tables describe every current field without repeating all coordinates. A portal threshold and its destination landing are different points and must be changed together when redesigning the map.

| Portal field | Default/example | Units/type | Meaning |
| --- | --- | --- | --- |
| `id` | ACCESS1, AUD0, M0, etc. | unique text | Identity used by route graphs, closures, output, and explicit admission memory. |
| `type` | access / door / stairs / exit / elevator | text | Connector behavior. Only first-floor exterior exit portals complete an evacuation. |
| `from` | aisle, rim, corridor, etc. | region ID | Source circulation state eligible to use this portal. |
| `floor`, `plan` | 0/main or 1/balcony | identifiers | Source floor and plan. |
| `x`, `y` | explicit JSON coordinates | metres | Threshold position in the source plan. These are authoritative positions. |
| `width` | family dependent | metres | Physical aperture, body fit, throughput, and observed queue delay estimate. |
| `evacuationAllowed` | true except ADA_W | boolean | Whether this connector belongs to the evacuation network. Elevator exclusion remains in force. |
| `angle` | explicit radians where supplied | radians | Polar orientation for relevant circular portal approaches; unlike the fraction-of-pi geometry lists. |
| `sourceZone` | orchestra on ACCESS portals | zone ID | Restrict an aisle transfer to the correct seating zone. |
| `toEntrance` | named landing | entrance ID | Destination for interior doors and access/stair transfers. This is how a balcony guest enters the first-floor plan. |
| `length` | 1.5 / 15 / 12 | metres | Access/stair traversal length; kept consistent with the sum of flights. |
| `flights` | [1.5], [7.5, 7.5], [12] | list of metres | Sequential connector flight distances and travel state. |
| `laneCount` | 1 or 2 | integer | Number of connector lanes with independent spacing and occupancy. |
| `laneDivider` | 0 or 0.1 | metres | Width subtracted before dividing the remaining connector width among lanes. |
| `normal` | {x: 0, y: 1}, etc. | unit vector | Outward normal of exterior threshold, used for crossing and tangent aperture fit. |
| `exitId` | MAIN, SIDE_E1, STAGE_E, etc. | text | Reporting aggregation. M0 through M4 all contribute to MAIN. |
| `rare` | true on side/stage routes | boolean | Descriptive metadata. There is no remaining familiarity coefficient or emergency-only toggle attached to this flag. |
| `prohibitedReason` | ADA elevator explanation | text | Human-readable reason; `evacuationAllowed` implements the restriction. |

| Portal family | Default | Units/type | Connection |
| --- | --- | --- | --- |
| ACCESS1 through ACCESS6 | six; width 1.3; length 1.5; flights [1.5]; one lane; divider 0 | metres | Orchestra aisle to corresponding LOGE_ACCESS entrance. |
| AUD0 through AUD8 | nine; width 1.35 | metres | Rim to corresponding CORRIDOR_AUD entrance. |
| F0 through F2 | three; width 1.65 | metres | Corridor to corresponding FOYER_F entrance. |
| M0 through M4 | five; width 1.75 each | metres | Foyer to exterior; combined MAIN width 8.75. |
| SIDE_E1, SIDE_E2, SIDE_W2, SIDE_W1 | four; width 1.35 | metres | Corridor directly to exterior; available throughout ordinary runs. |
| BACK_E, BACK_W | two; width 1.6; length 15; flights [7.5, 7.5]; two lanes; divider 0.1 | metres | Balcony rim to FOYER_BACK landing. |
| STAGE_E, STAGE_W | two; width 1.15; length 12; flights [12]; one lane; divider 0 | metres | Balcony rim to corresponding GROUND_STAGE landing on floor 0. |
| GROUND_STAGE_E, GROUND_STAGE_W | two; width 1.15 | metres | Stage-side first-floor landing to exterior. |
| ADA_W | one; width 1.2; evacuationAllowed false | metres | Elevator recorded in map but unavailable for evacuation. |

Each `geometry.entrances.<id>` supplies matching `id`, `plan`, `floor`, `region`, `x`, `y`, and `normal: {x,y}`. `zone` and `aisleAngle` are also supplied for aisle landings; `aisleAngle` is radians. The normal points into the destination and determines landing-depth probes and lane offsets. Current landings are six LOGE_ACCESS entrances, nine CORRIDOR_AUD entrances, three FOYER_F entrances, two FOYER_BACK entrances, and two GROUND_STAGE entrances. All are on the first floor. Interior transitions do not mark a guest evacuated.

Portal `enabled`, `tokens`, `passed`, and connector lane contents are runtime state, not additional independent world parameters. Closures alter enabled state; thresholds still require the appropriate source region, body fit, and crossing conditions.

## Retained geometry and descriptive fields

| Parameter | Default | Units/type | Current status |
| --- | --- | --- | --- |
| `geometry.auditoriumR` | 22.2 | metres | Archived geometry construction and related legacy/display calculations. Current seating zones and explicit regions are authoritative. |
| `geometry.corridorR` | 25.2 | metres | Retained legacy route estimates and archived geometry. Does not move the current corridor or its explicit portals. |
| `geometry.balconyR` | 22.75 | metres | Archived geometry/display field; current balcony bounds are explicit. |
| `geometry.auditoriumDoors` | [0.06, 0.17, 0.28, 0.39, 0.5, 0.61, 0.72, 0.83, 0.94] | fractions of pi | Archived portal generation. Current AUD portals have explicit coordinates and radians. |
| `geometry.foyerDoors` | [0.44, 0.5, 0.56] | fractions of pi | Archived portal generation. Current F portals are explicit. |
| `geometry.exits[]` | four side entries width 1.35; MAIN width 8.75 | summary objects | Each has `id`, `angle`, `width`, `type`. Used by archived geometry and retained legacy route estimates; changing these does not relocate current explicit exits. |
| `geometry.stairs[]` | BACK_E/W width 1.6 length 15; STAGE_E/W width 1.15 length 12 | summary objects | Each has `id`, `angle`, `type`, `width`, `length`; angles are fractions of pi. Archived construction metadata; current portal objects control transfers. |
| `geometry.exteriorContext.simulated` | false | boolean | Descriptive context, not an outdoor-motion feature switch. |
| `geometry.exteriorContext.monumentalStaircase` | x 0; y 43.5; width 14 | metres | Context metadata for outdoor stairs. Current illustration also contains its own drawing constants. |
| `geometry.exteriorContext.porticoStaircases` | 2 | count | Descriptive context. Outdoor staircase traversal is outside the simulated completion process. |
| `geometry.exteriorContext.note` | threshold-completion explanation | text | Descriptive note. |

## Optional crowd managers

Settings below live in `crowdManagers`, not the policy-settings object. Exactly six stationary managers are supported. Without explicit positions, automatic placement greedily improves geometric signal coverage over all seats. This is an initialization heuristic, not a guarantee of minimum evacuation time. The simulation-based optimizer can then search placements. Managers are physical obstacles but do not add audience participants or moving peer observations.

| Parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `enabled` | false | boolean | Opt into crowd-manager bodies, information, and guidance. Students suppress these effects. Closure scenarios remain independently meaningful. |
| `count` | 6 | people | Must equal six. |
| `positions` | empty list | candidate IDs | Empty selects automatic initialization; otherwise supply six distinct feasible candidate IDs. Arbitrary x/y positions are not the placement interface. |
| `strength` | 12 | utility units | Maximum manager utility bonus at zero distance before memory attenuation. Strictly positive. This is not acceleration. |
| `decayLength` | 8 | metres | Signal decay length in exp(-distance/decayLength). The implementation is exponential, not inverse-square. |
| `communicationRange` | 12 | metres | Finite same-floor hearing/guidance range, also requiring line of sight. |
| `memorySeconds` | 60 | seconds | Guidance memory duration and exponential age-decay time scale; stale remembered guidance expires. |
| `managerRadius` | 0.2025 | metres | Stationary staff body radius, affecting feasible candidate sites and physical clearance. |
| `requireBothFloors` | true | boolean | Require at least one manager on each floor during initialization, layout validation, and search. |
| `showCoverage` | false | boolean | GUI coverage outline only; the drawn outline is not a replacement for actual wall occlusion tests. |
| `closures` | empty list | events | Schedule disabled evacuation portals. Physical availability and individual knowledge are separate states. |
| `closures[].portalId` | required | portal ID | Evacuation-allowed connector to disable. |
| `closures[].at` | 0 | seconds | Nonnegative time of closure. Events are permanent; reopening and partial width loss are not represented. |
| `closures[].notifyAfter` | null | seconds or null | Null gives no automatic staff notification; zero informs staff immediately; a positive value delays notification after closure. Local discovery can still occur. |

Every occupied seat has an initially assigned manager. If that manager can currently communicate with the person, their instruction has priority over other audible managers. Otherwise the strongest eligible fallback manager is used, with deterministic tie-breaking. The next recommended action follows the manager's current shortest-distance route knowledge. Finite authority means ordinary utility can still favor a different action. Guidance strength depends on signal at reception and memory age; guests are not physically pulled toward the manager. A per-person responsiveness factor is initialized to one and is not a separate exposed configuration field.

Candidate sites discretize staff placement, not pedestrian positions. They are sampled in aisles, circulation rings, and the foyer, excluding seats, portal approaches, incompatible overlaps, and narrow placements. Automatic initialization considers every seat, so it does not exploit the particular sampled audience occupancy.

## Optional students and LED strips

Student mode chooses the currently shortest known feasible distance route, including connector distances, rather than maximizing behavioral utility. It supplies full layout knowledge but not automatic omniscience about unexpected closures. Students still discover obstructions and reroute. It does not explicitly optimize congestion, expected clearance time, or the social optimum. Ordinary physical movement remains the same. Crowd-manager and LED options do nothing to student movement.

LED settings live in `ledStrips`. An enabled strip network supplies a shortest-distance next-target recommendation and a constant utility bonus to the indicated action. The remaining behavioral utility stays active. Continuous strip coverage along the modeled walking network is assumed; exposure is not a photometric or distance-to-strip model.

| Parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `ledStrips.enabled` | false | boolean | Opt into LED instructions for nonstudents. Does not create managers. Requires current two-plan geometry and local behavior. |
| `ledStrips.strength` | 12 | utility units | Nonnegative constant bonus for the indicated next action. Comparable to the maximum near-manager bonus, but without spatial or memory decay. Zero removes both instructions and their bonus. It is not a physical force or speed multiplier. |
| `ledStrips.adaptive` | true | boolean | Controller instantly reads currently disabled evacuation portals and updates shortest routes. This is an explicit controller-information assumption; guests receive a next-target instruction, not a global closure list. False freezes the initial strip-network closure knowledge. A person rejects a stale instruction if they already know its route is blocked. |
| `ledStrips.showStrips` | true | boolean | Draw the green route network, including curves around annular holes and local row/aisle branches. Read-only display; does not alter random draws or decisions. |

Managers and LEDs may coexist for nonstudents, adding their separate utility bonuses. Students suppress both. Neither guide guarantees compliance at finite strength. Optional LED counters report decisions offered guidance, decisions following it, and choices changed by its bonus; these are outputs, not parameters. The full mathematical explanation is in `LED_GUIDANCE.tex`.

## Fixed implementation constants that also affect behavior

The following are code constants, not JSON tuning parameters. Changing them requires a code change and should be recorded as a model change.

| Constant | Default | Units/type | Effect |
| --- | --- | --- | --- |
| Door refill | 1.3 times width | people/second | Token throughput coefficient when doorCapacity is enabled. |
| Door token initialization/cap | max(1, 1.2 times width) / max(1, 1.35 times width) | tokens | Initial burst and accumulated-token ceiling. |
| Interior portal proximity | 0.65 | metres | Proximity condition for attempting transfer; aperture fit also uses body radius and 0.01 m padding. |
| Connector speed | access max(0.4, desired speed); stairs max(0.4, 0.7 times desired speed) | m/s | Transfer travel rate. Flights are timed rather than drawn as planar walking. |
| Connector headway | max(0.35, (2 radius + 0.1)/speed) | seconds | Minimum same-lane entry separation. |
| Connector occupancy | max(1, floor(total length/(2 radius + 0.1))) | people/lane | Lane occupancy cap. Lane width must exceed body diameter plus 0.02 m. |
| Landing probes | 0, 0.25, 0.5, 0.75 | metres | Candidate depths along landing normal, combined with lane offset and clearance tests. |
| Hard separation factor | 1.005 on squared diameter sum | dimensionless | Small additional margin in body exclusion. |
| Maximum displacement | 0.7 | metres/tick | Per-tick movement cap. This is another reason large dt changes cannot be treated as pure playback changes. |
| Panic envelope time | 60 | seconds | Growth time constant of the panic shock envelope. |
| Moving norm cutoff | 0.12 | m/s | Minimum neighbor motion used in direction-based norm observations. |
| Opposing direction cutoff | dot product below -0.15 | dimensionless | Identify opposing motion for local norm features. |
| Progress anchor displacement | 0.12 | metres | Displacement needed to refresh anchored progress for stalled steering. |
| Waypoint tolerance | 0.025 | metres | Small-goal arrival tolerance. |
| Predictive steering directions | 0, plus/minus 20, 40, 65, 90, 120, and 180 | degrees | Candidate directions, tested at full and half speed, with directional scoring constants. |
| Row tolerances | radial 0.07; angular 0.012 | metres; radians | Constrain seat-row movement and related geometry checks. |
| Route knowledge cache | 64 | fields | Bounded shortest-route knowledge-field cache; a performance control, not a behavioral weight. |

Small numerical epsilons throughout geometry and force code protect divisions, boundary comparisons, and degeneracies. They should not be interpreted as empirical psychological parameters.

## CLI overrides and experiment parameters

`python run.py --gui` opens the desktop application; `python run.py` runs headlessly. Relative output paths are resolved under the Python port directory. World and settings JSON files have different schemas: `--config` loads a world, while `--settings` overrides the bundled policy constructor settings.

| CLI parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `--population`, `--n`; `--seed`; `--dt`; `--max-seconds` | world values | run controls | Override the corresponding world fields. |
| `--ticks` | absent | ticks | Additional tick-count stopping limit. |
| `--config` | bundled world | JSON path | Load a complete world configuration. |
| `--settings` | bundled policy settings | JSON path | Override policy settings. |
| `--policy` | bundled policy | Python path | Load trusted editable policy code. |
| `--disable-portal` | none | repeatable ID | Disable specified portal(s) after setup. |
| `--students`, `--no-students` | world setting | flags | Explicit student-mode override. |
| `--crowd-managers`, `--no-crowd-managers` | world setting | flags | Explicit manager-mode override. |
| `--manager-settings` | absent | JSON path | Load the optional crowd-manager settings object. |
| `--led-strips`, `--no-led-strips` | world setting | flags | Explicit LED-mode override. |
| `--led-strength` | world/module setting | utility units | Override LED strength. Does not itself enable LED mode. |
| `--led-settings` | absent | JSON path | Load the optional LED settings object. |
| `--no-collisions`, `--no-regions`, `--no-door-capacity` | absent | flags | Disable corresponding limits. |
| `--output`, `--csv` | absent | output paths | Write detailed run JSON and agent CSV. |
| `--include-weights` | false | flag | Append four behavioral weight columns to CSV; does not change behavior. |
| `--gui`, `--animate` | false | flags | Launch desktop editor/viewer. |

The manager optimizer separates search settings from physical model parameters. Search changes which layouts are evaluated; it does not change audience mechanics. Its finite placement domain and heuristic search provide a best tested layout, not a proof of global optimality.

| Optimizer parameter | Default | Units/type | Meaning |
| --- | --- | --- | --- |
| `--n` | 300 | guests | Audience size per evaluation. |
| `--config` | bundled world | JSON path | Base building and run configuration for evaluations. |
| `--training-seeds` | [2026] | seeds | Repeated audience/noise samples used to rank layouts. |
| `--validation-seeds` | [7] | seeds | Disjoint held-out samples for validation; not used to select the layout. |
| `--search-population` | 6 | layouts | Number of layouts retained in the population; at least two. |
| `--generations` | 3 | iterations | Number of generations after the initial population. |
| `--search-seed` | 314159 | seed | Independent randomness for layout search. |
| `--max-seconds` | 180 | seconds | Evaluation horizon; incomplete runs remain failures/censored outcomes. |
| `--manager-settings`, `--settings` | optional overrides | JSON paths | Manager and bundled-policy constructor settings for evaluations. |
| `--scenarios` | configured closures, else open | JSON path | Named scenarios with positive weights and closure-event lists. Weights are normalized over scenarios and evaluation seeds. |
| `--output`; `--layout-output` | required report; optional layout | paths | Save evaluation report and an optionally reusable manager configuration. |

Optimizer scenario records use `name`, `weight` (default one), and `closures` (default empty). Closure entries use the schema above. Ranking first penalizes incomplete-run frequency, then remaining audience fraction, then restricted clearance. Mean full-clearance time is meaningful as the primary clearance objective only when all relevant runs finish. Student mode is rejected for manager optimization because it suppresses manager effects.

`compare_student_audiences.py` exposes `--populations` (default 300 and 600), `--seeds` (default 2026, 7, 17), `--max-seconds` (180), optional `--dt`, `--random-stream` (paired by default, or original), and required `--output-dir`. These control an analysis batch and its records, not new movement parameters. Keep integration dt, physics, seed sets, occupancy, stopping horizon, and random-stream mode explicit when interpreting any future comparison.

## Implementation sources

`config.py` validates world schemas and public run limits; `engine.py` samples people, advances time, enforces collisions and portal transfers, and assembles active options. `geometry.py` and `plans.py` generate seats and test geometry. `perception.py` controls visibility. `behavior.py` constructs local actions, observations, and features, then combines supplied weights, shocks, and guidance. `user_model.py` samples weights and shocks and selects behavioral and force modes; `social_force.py` implements physical forces. `crowd_routes.py` provides shortest-distance route fields; `crowd_managers.py` adds optional staff and closure knowledge; `led_guidance.py` adds optional constant utility instructions. CLI, viewer, optimizer, and comparison scripts add execution, display, and experiment controls. The defaults and source remain authoritative if future edits change this reference.
