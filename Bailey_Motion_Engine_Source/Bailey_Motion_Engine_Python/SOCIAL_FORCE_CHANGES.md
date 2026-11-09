# Social Force Component implementation

Historical change log: the later familiarity-removal revision supersedes all references below to five-factor utility and familiarity rewards. Current utility uses four weights (T, P, N, S); see [FAMILIARITY_REMOVAL.md](FAMILIARITY_REMOVAL.md).

This change implements the supplied image's three acceleration terms in the
current Python two-plan model. The default is `socialForceMode: "manuscript"`.
The original JavaScript files and archived legacy-world trajectories are retained.

## Equations and conventions

```text
f_des = (v0 * u_to_waypoint - v) / tau
f_obs = sum_w A * exp(-d_iw / r_i) * n_iw

x_hat_ij = (x_j - x_i) / distance(i, j)
v_ij = v_i - v_j
D_ij = lambda * v_ij + x_hat_ij
D_hat_ij = D_ij / |D_ij|
N_hat_ij = (-D_hat_y, D_hat_x)
theta_ij = atan2(cross(D_hat_ij, x_hat_ij), dot(D_hat_ij, x_hat_ij))

f_ij = -exp(-distance(i,j) / |D_ij|) * (
    exp(-(n_prime * theta_ij * |D_ij|)^2) * D_hat_ij
    + sign(theta_ij) * exp(-(n * theta_ij * |D_ij|)^2) * N_hat_ij
)
f_int = sum_j f_ij

dv/dt = f_des + f_obs + f_int
v_raw_next = v + dt * (f_des + f_obs + f_int)
```

These quantities are accelerations, as indicated by `dv/dt` in the supplied
image. The path's local waypoint supplies the desired unit direction toward the
selected egress; it does not aim straight through intervening walls. `tau` is a
shared constant. `N_hat` is the counterclockwise normal and `theta` is signed.
Distances to walls mean pedestrian-centre-to-obstacle-surface distances, without
subtracting body radius. These are explicit implementation conventions.

## Complete code and behavior change list

| File / component | Change | Effect |
|---|---|---|
| `bailey_motion/social_force.py` (new) | Separate functions for desired, obstacle, interpersonal acceleration, their sum, and Euler integration | Each equation is directly inspectable and numerically testable |
| `social_force.desired_acceleration` | Use the actual positive `relaxationTime`, without the old 0.05 s floor | Implements the stated constant `tau` exactly |
| Same function | At an exact waypoint, use zero desired velocity and retain `-v/tau` | Brakes a moving unit instead of discarding all force terms through the old 0.025 m early return |
| `social_force.obstacle_acceleration` | Sum `A * exp(-d/r_i) * normal` over explicit obstacle contacts | Implements the obstacle-force sum with a visible obstacle count |
| `social_force.comfort_distance` | Prefer `agent.params.comfortDistance`, falling back to the policy's `comfortDistance` | Supports individual `r_i` without adding random draws in the default world |
| Same function and obstacle calculation | Remove the old 0.05 m minimum comfort-distance clamp; require a positive finite value | Small positive comfort distances now mean what the user specifies |
| `social_force.interaction_acceleration` | Explicit relative position, relative velocity, interaction direction, signed angle, normal, longitudinal and lateral exponentials | Implements the image's anisotropic pairwise force |
| Same function | Remove `interactionStrength * (0.75 + 0.5 * norms)` in manuscript mode | Uses the equation's implicit coefficient one; the sampled `norms` trait no longer rescales physical repulsion |
| Same function | Skip self, exited units, and units on other floors | Restricts interpersonal forces to eligible pedestrians on the same plan |
| Same function | Skip coincident positions and use the zero-force limit for vanishing `D`; numerical tolerance is `1e-12` | Prevents undefined unit vectors without inventing a force direction; coincident bodies still require hard collision handling |
| `plans.obstacle_contacts` (new) | Return named surface-distance / unit-normal records for aisle edges and region bounds | Makes the represented obstacle set `W` explicit; surfaces remain schematic analytical proxies |
| Same function | Use centre-to-surface aisle distances rather than subtracting radius and clearance | Makes `d_iw` consistent across aisle and wall terms |
| Same function | Include the orchestra barrier surface outside its six access openings | Adds soft barrier repulsion to the existing hard barrier constraint |
| Same function | Suppress a boundary-wall contact across any enabled, eligible exterior opening, based on aperture width rather than selected-door proximity | Prevents an artificial wall force across a physically open door; disabling that door restores the wall term |
| `user_model.UserModel` | Add `manuscript_forces` and `force_components` | Select the new equations for current plans while retaining legacy comparisons and exposing the three terms through the policy API |
| `UserModel.setup` | Validate each supplied individual comfort distance | Rejects invalid sampled values before a simulation starts |
| `UserModel.compute_velocity` | Dispatch manuscript mode to `compute_social_force_velocity` | Integrates the explicit three-term ODE in the live simulation |
| `UserModel.compute_social_force_velocity` (new) | Evaluate all three terms even at an exact waypoint | Removes the old early return that suppressed obstacle/neighbor forces and braking |
| Same function | Preserve speed caps, nearby-waypoint overshoot limiting, and optional local steering after raw Euler integration | Retains existing movement safeguards; at exactly zero waypoint distance there is no distance-based cap, so braking/repulsion can act |
| Same function | Save the latest force evaluation in `agent.data.socialForce` | Inspector and full JSON show evaluation time/position, velocity before integration, waypoint, three accelerations, sum, comfort distance, counts, raw Euler velocity, capped velocity, and final requested velocity |
| `default_policy_settings.json` | Add `socialForceMode: "manuscript"` | Enables the supplied equations by default for the current layout; `"legacy"` restores pre-change force calculations |
| `UserModel.__init__` | Validate mode, positive `relaxationTime`, `comfortDistance`, `interactionRange`, `maxSpeedFactor`, and nonnegative `obstacleStrength`, `interactionLambda`, `interactionN`, `interactionNPrime` | Rejects nonfinite, wrong-type, and invalid coefficients instead of silently flooring them |
| `force_only_settings.json` (new) | Set manuscript mode with `localAvoidance: false` | Provides a runnable experiment without the previously added sidestepping velocity search |
| `tests/test_social_force.py` (new) | Add 15 numerical and integration tests | Checks hand-calculated vectors, signed-angle behavior, Euler integration, singular cases, individual comfort distance, openings/barrier contacts, hidden-multiplier removal, diagnostics, and unchanged default initialization/RNG |
| `README.md` and this file | Document equation mapping, settings, inspector fields, comparison runs, limitations, and this full change list | Makes behavior and reproduction instructions available alongside the code |
| `results/social-force-*` (generated) | Save two full 300-person JSON/CSV runs and a verification report | Records outcomes and checks without overwriting earlier baseline artifacts |

## Running it

From this Python project's directory:

```powershell
python run.py --gui
python run.py --population 300 --seed 2026 --max-seconds 180
python run.py --population 300 --settings force_only_settings.json --max-seconds 180
```

The last command disables local sidestepping. Hard body exclusion, row projection,
speed limits, the engine's movement fallbacks, door capacity, and named stair
transfers remain active. It is an experiment using the supplied forces with
these mechanics, rather than an unconstrained ODE solver. Disabling avoidance
does not guarantee a complete evacuation.

For a pre-change force comparison, set `socialForceMode` to `"legacy"` in the
GUI's Policy settings tab or a settings JSON override. Archived `legacy_world.json`
always uses its original JavaScript-reference force implementation.

To assign an individual comfort distance distribution, add this member to the
world JSON's existing `distributions` object:

```json
"comfortDistance": {"type": "normal", "mean": 0.15, "sd": 0.03, "min": 0.03}
```

`sd` is standard deviation. This is an example assumption, not a fitted
distribution. Adding a sampled trait consumes extra seeded random draws and can
therefore change other initialization draws; the bundled default adds no trait
and keeps the original population and utility weights.

## Scope of the implementation

`interactionRange` remains a finite neighbor-search cutoff, default 2.6 m, so the
sum is evaluated over that neighborhood, not every person in the building.
Obstacle geometry remains the existing schematic region/aisle surfaces plus the
orchestra barrier. Individual seat backs, full CAD surfaces, door-jamb contact,
and continuous force-based movement on staircase flights are not represented.
Stairs retain the named, finite-capacity timed transfers.

The latest force diagnostic describes a calculation at its recorded time and
position, not a complete trajectory history. The raw Euler velocity can differ
from the capped request, optional steering output, and actual velocity after
engine constraints. The five utility weights and exit-choice formulas are
unchanged. Forces, geometry, cutoff, and steering parameters remain uncalibrated.

## Verification results

All 61 headless tests and the actual hidden-window Tk desktop-control test passed
(62 total). The 15 new equation tests are in `tests/test_social_force.py`.

Two 300-person runs with local avoidance enabled fully clear in approximately
63.6 seconds (seed 2026) and 73.3 seconds (seed 7). All 600 units have unique IDs
within their runs and first-floor exterior crossing events. Their sampled traits
and utility weights match the corresponding pre-change baselines. All saved
force sums and raw Euler velocities were checked numerically. The separate
30-person force-only-settings run clears in approximately 44.8 seconds.

`results/social-force-verification.json` records the checks; the saved JSON/CSV
artifacts retain the full runs. These times describe assumed model behavior,
not a validated physical prediction.
