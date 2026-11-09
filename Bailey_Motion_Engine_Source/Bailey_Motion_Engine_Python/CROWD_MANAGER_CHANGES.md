# Optional crowd-manager implementation

Crowd managers are **off by default**. `default_world.json`, `default_policy_settings.json`, the four behavioral weights, the 3-second decision interval, and the JavaScript engine are unchanged. All new physical and behavioral mechanisms below run only when explicitly enabled. Scheduled closure experiments can also run without managers.

## Functional changes

1. Added `crowd_routes.py`: a directed graph of aisle ends, region connections, portal departures and named landings. Row-side actions attach through legal aisle ends; they cannot cut across seating or floors.
2. Added physical distance costs: analytic chord/tangent/arc distances inside current annular sectors, Euclidean distances in rectangles, declared lengths on stairs/access connectors, and departure-to-landing lengths on ordinary doors. Nanometre-scale boundary snapping stabilizes tangent calculations.
3. Added reverse multi-source Dijkstra routing, stable ties, unreachable-state handling, and an LRU cache for up to 64 sets of known closures. Portal actions include their actual transfer before downstream routing.
4. Added an all-open reference route and responsible manager for every generated seat. Initial routes are not claims about surveyed distances. Responsibility does not imply immediate communication coverage.
5. Added deterministic feasible staff candidates, avoiding seats, portal approaches, barrier walls and mutual overlap. The current geometry yields 110 candidates. Default placement requires representation on both occupied floors; the other four positions may be distributed by the optimizer.
6. Added a deterministic greedy coverage initializer using all seats. Coverage supplies a starting layout; simulated evacuation outcomes rank optimized layouts.
7. Added exactly six stationary physical staff discs, with negative IDs. They participate in audience collision avoidance/forces, without counting as audience, behavioral peers, moving evacuees or exit statistics.
8. Added manager selection with initial-assignment priority: among receivable managers, prefer the originally assigned manager. If it is unavailable because of range, floor or walls, use the strongest receivable manager; stable IDs break signal ties. Fallback does not change the original assignment. Signals do not stack, and the selected manager's actual distance-decayed signal determines its bonus. Earlier saved experiments used strongest-signal selection without assignment priority; their timings and placements have not been recomputed.
9. Added an explicit utility bonus for the recommended action. Existing behavioral preferences remain four-dimensional; responsiveness starts at one, without changing preference draws. A finite bonus does not force obedience.
10. Added instruction-based target discovery and remembered portal sequences. An instruction can advance across regions without new global knowledge; its authority decays and expires. Learned target locations remain known after authority expires.
11. Added permanent scheduled portal closures with immediate, delayed or absent automatic staff notification. Physical closure precedes motion; staff and guests retain separate knowledge. Local discovery and guest reports can inform managers earlier than scheduled notification. Partial obstruction and reopening are not implemented.
12. Added decision diagnostics: received instructions, guidance bonuses, responsibilities, adherence counters, all seat routes and manager knowledge. Optional reports include time to 95% exited and peak observed queue sizes, with explicit nulls for incomplete results.
13. Added a discrete genetic search with an isolated search RNG, unique six-site chromosomes, tournament selection, crossover, mutation, feasibility rejection, elitism and evaluation caching. It finds a best-known layout; it does not prove a global optimum.
14. Added a failure-aware lexicographic objective: failure probability, mean remaining fraction, then restricted clearance time. Incomplete runs are retained rather than silently excluded.
15. Added weighted obstruction scenarios, disjoint training/validation seeds, held-out guided/no-manager comparisons, audience fingerprints, and optional counter-keyed policy shocks for matched random streams. Ordinary policy randomness is unchanged by default.
16. Added CLI switches `--crowd-managers`, `--no-crowd-managers` and `--manager-settings`, plus a separate optimizer launcher and reusable optimized layout output.
17. Added a GUI checkbox applied on reset, physical manager markers, optional range outlines, and the selected guest's instruction sequence. The GUI explicitly shows mode, people reached, guided decisions, choices changed by the utility bonus, and precise final clearance/T95. Detailed per-agent guidance remains available in the inspector. Range outlines do not imply visibility through walls.
18. Added separate manager settings, a delayed-blockage example, scenario definitions, mathematical documentation, focused tests, and README usage instructions.

## Verification scope

Every real simulation/engine verification in this work uses **300 audience members**. The focused tests cover disabled-mode identity, matched audience initialization, routing against independent Bellman relaxation, analytic distances, causal obstruction knowledge, physical staff/peer separation, utility accounting, memory, finite exports, search protocol, and headless rendering.

The baseline run's pre-change 100-tick export fingerprint is checked against the post-change baseline. Existing low-population test suites are not run because the user requested n=300 for executions. GUI rendering and control wiring receive headless checks, and `test_crowd_gui_300.py` verifies real hidden Tk controls with 300 guests. No LaTeX compiler is required to read the source specification.

Results under `results/crowd-*` distinguish initial-layout smoke checks from search/held-out evaluations. A small search verifies the pipeline; it cannot establish robust placement quality. Numerical outcomes and checks are recorded in `results/crowd-final-verification.json` when verification finishes.
