"""Agent-based auditorium exit model, using only the Python standard library.

Geometry, observation, utility, and movement are separate extension points.
Coordinates and time are abstract cells and steps, not meters and seconds.
"""
from __future__ import annotations

import copy
import math
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping, Sequence, TypeVar

T = TypeVar("T")
# These five names define both the behavioral vector and the CSV column order.
# They are individual preferences, not probabilities, and need not sum to one.
WEIGHT_NAMES = ("time", "habit", "peer", "norm", "switching")


def require(condition: bool, message: str) -> None:
    # Configuration failures stop the experiment before invalid states propagate.
    if not condition:
        raise ValueError(message)


def integer(value: Any, minimum: int, name: str) -> None:
    # Python considers bool a subclass of int; reject True/False as counts anyway.
    require(type(value) is int and value >= minimum,
            f"{name} must be an integer >= {minimum}.")


class Random:
    """Seeded xorshift32 + Box-Muller; same draw order as model.js.

    `normal` takes VARIANCE. Negative and above-one draws are retained.
    This generator supports repeatable experiments, not cryptography.
    """

    def __init__(self, seed: int = 42):
        # Keep a 32-bit state. Zero would remain zero forever under xorshift,
        # so that seed uses a fixed nonzero replacement instead.
        self.state = (seed & 0xFFFFFFFF) or 0x9E3779B9

    def uniform(self) -> float:
        # Explicit masks reproduce JavaScript's 32-bit integer operations.
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        # The half-unit offset avoids exactly 0 or 1, making log(U) safe below.
        return (self.state + 0.5) / 4294967296

    def normal(self, mean: float = 0.0, variance: float = 1.0) -> float:
        require(math.isfinite(mean) and math.isfinite(variance) and variance >= 0,
                "Normal mean must be finite and variance finite and nonnegative.")
        # Box-Muller converts two uniform draws into one Gaussian draw.
        # sqrt(variance) is the standard deviation; do not pass it as variance.
        # Draws are neither clipped nor cached, preserving the reference draw order.
        return (mean + math.sqrt(variance) * math.sqrt(-2 * math.log(self.uniform()))
                * math.cos(2 * math.pi * self.uniform()))

    def pick(self, items: Sequence[T]) -> T:
        return items[math.floor(self.uniform() * len(items))]

    def shuffle(self, items: list[T]) -> list[T]:
        # Fisher-Yates shuffles the supplied list in place. Initialization uses
        # a copy of spawn cells so the building's own list remains unchanged.
        for i in range(len(items) - 1, 0, -1):
            j = math.floor(self.uniform() * (i + 1))
            items[i], items[j] = items[j], items[i]
        return items


@dataclass
class GeometryConfig:
    """BUILDING PARAMETERS: replace this square with a measured layout later.

    Obstacles: {x, y, width, height} interior rectangles.
    Optional exits: [{name, cells: [{x, y}, ...]}, ...].
    Explicit exits override the four centered doors and exit_width.
    """

    # Coordinates are zero-based. The outermost cells are boundary walls;
    # size includes those walls, leaving (size - 2)^2 interior cells initially.
    type: str = "square"
    size: int = 31
    exit_width: int = 1
    # Factories prevent independent configurations from sharing mutable objects.
    obstacles: list[dict[str, int]] = field(default_factory=list)
    exits: list[dict[str, Any]] | None = None

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> GeometryConfig:
        return cls(**_translate(values, {"exitWidth": "exit_width"}, cls))


@dataclass
class SimulationConfig:
    # These are experiment defaults, not values estimated from observed data.
    participants: int = 150
    seed: int = 42
    max_steps: int = 5000
    # Each of the five weights is sampled independently once per agent.
    weight_mean: float = 0.5
    weight_variance: float = 1.0
    # Neighborhood distance is Manhattan distance, in abstract grid cells.
    observation_radius: int = 5
    # Sustained blockage triggers reconsideration; the interval limits its rate.
    reconsider_after: int = 10
    reconsider_every: int = 8
    # Set exploration to zero for strict highest-utility target selection.
    exploration_probability: float = 0.02
    # Friction applies only when multiple agents request the same empty cell.
    conflict_friction: float = 0.05
    # Normalize perceived time into a utility feature; this does not turn steps
    # into seconds. The panic time scale controls how quickly its envelope grows.
    time_reference: float = 10.0
    panic_time_scale: float = 100.0
    # Unlike weight_variance, this parameter explicitly stores STANDARD DEVIATION.
    residual_std: float = 0.2
    # Setting a scale to zero disables that extra term without resampling weights.
    distance_scale: float = 1.0
    congestion_scale: float = 1.0
    panic_scale: float = 1.0
    geometry: GeometryConfig = field(default_factory=GeometryConfig)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> SimulationConfig:
        """Accept Python snake_case and existing JavaScript camelCase JSON."""
        translated = _translate(values, CONFIG_ALIASES, cls)
        if "geometry" in translated:
            geometry = translated["geometry"]
            translated["geometry"] = (copy.deepcopy(geometry) if isinstance(geometry, GeometryConfig)
                                      else GeometryConfig.from_dict(geometry))
        return cls(**translated)

    def validate(self) -> None:
        # Bounds apply to experiment settings, not to the realized normal weights.
        for name, minimum in (("participants", 0), ("seed", 0), ("max_steps", 1),
                              ("observation_radius", 0), ("reconsider_after", 1),
                              ("reconsider_every", 1)):
            integer(getattr(self, name), minimum, name)
        require(self.seed <= 0xFFFFFFFF, "seed must fit in an unsigned 32-bit integer.")
        for name in ("weight_mean", "weight_variance", "residual_std", "distance_scale",
                     "congestion_scale", "panic_scale", "time_reference", "panic_time_scale",
                     "exploration_probability", "conflict_friction"):
            value = getattr(self, name)
            require(type(value) in (int, float) and math.isfinite(value), f"Invalid {name}.")
            if name != "weight_mean":
                require(value >= 0, f"{name} must be nonnegative.")
        for name in ("time_reference", "panic_time_scale"):
            require(getattr(self, name) > 0, f"{name} must be positive.")
        for name in ("exploration_probability", "conflict_friction"):
            require(getattr(self, name) <= 1, f"{name} must lie in [0, 1].")
        require(isinstance(self.geometry, GeometryConfig), "geometry must be a GeometryConfig.")

    def to_dict(self) -> dict[str, Any]:
        # Keep config exports compatible with the shared camelCase JSON format.
        result = asdict(self)
        result["geometry"] = {("exitWidth" if k == "exit_width" else k): v
                              for k, v in result["geometry"].items() if v is not None}
        reverse = {v: k for k, v in CONFIG_ALIASES.items()}
        return {reverse.get(k, k): v for k, v in result.items()}


CONFIG_ALIASES = {
    "maxSteps": "max_steps", "weightMean": "weight_mean", "weightVariance": "weight_variance",
    "observationRadius": "observation_radius", "reconsiderAfter": "reconsider_after",
    "reconsiderEvery": "reconsider_every", "explorationProbability": "exploration_probability",
    "conflictFriction": "conflict_friction", "timeReference": "time_reference",
    "panicTimeScale": "panic_time_scale", "residualStd": "residual_std",
    "distanceScale": "distance_scale", "congestionScale": "congestion_scale", "panicScale": "panic_scale",
}


def _translate(values: Mapping[str, Any], aliases: dict[str, str], cls: type) -> dict[str, Any]:
    # Accept both naming conventions, but reject typos and duplicate aliases.
    # Deep copies prevent caller-owned lists/dicts from changing a live experiment.
    require(isinstance(values, Mapping), f"{cls.__name__} must be a JSON object or mapping.")
    allowed = {f.name for f in fields(cls)}
    result = {}
    for key, value in values.items():
        name = aliases.get(key, key)
        require(name in allowed, f"Unknown {cls.__name__} setting: {key}")
        require(name not in result, f"Duplicate setting: {name}")
        result[name] = copy.deepcopy(value)
    return result


class Building:
    """GEOMETRY EXTENSION POINT: occupancy, doors, and navigation connectivity.

    Navigation uses simulator-known BFS fields. This assumes route assistance
    around obstacles; it does not simulate discovery of an unfamiliar floor plan.
    Decision distance is Manhattan distance and crowd information is local.
    """

    def __init__(self, config: GeometryConfig):
        require(config.type == "square", "Only square geometry is currently supported.")
        integer(config.size, 7, "Room size")
        self.size = config.size
        self.cell_count = self.size ** 2
        # Geometry is stored as flat arrays indexed by y * size + x.
        # walkable distinguishes free floor/doors from walls and obstacles.
        # exit_at stores a door ID, or -1 for any cell that is not a door.
        self.walkable = [False] * self.cell_count
        self.exit_at = [-1] * self.cell_count
        for y in range(1, self.size - 1):
            for x in range(1, self.size - 1):
                self.walkable[self.index(x, y)] = True
        # Rectangular obstacles remove floor cells before doors and routes are built.
        require(isinstance(config.obstacles, list), "obstacles must be a list.")
        for rect in config.obstacles:
            for key in ("x", "y", "width", "height"):
                require(isinstance(rect, dict) and key in rect, f"Obstacle needs {key}.")
                integer(rect[key], 1, f"Obstacle {key}")
            require(rect["x"] + rect["width"] <= self.size - 1 and
                    rect["y"] + rect["height"] <= self.size - 1,
                    "Obstacle must lie inside the boundary walls.")
            for y in range(rect["y"], rect["y"] + rect["height"]):
                for x in range(rect["x"], rect["x"] + rect["width"]):
                    self.walkable[self.index(x, y)] = False
        if config.exits is None:
            # Without an explicit door list, center equal-width doors on four walls.
            integer(config.exit_width, 1, "Exit width")
            require(config.exit_width <= self.size - 2, "Exit width exceeds wall length.")
            start = (self.size - config.exit_width) // 2
            axis = range(start, start + config.exit_width)
            self.exits = [
                {"name": "North", "cells": [{"x": x, "y": 0} for x in axis]},
                {"name": "East", "cells": [{"x": self.size - 1, "y": y} for y in axis]},
                {"name": "South", "cells": [{"x": x, "y": self.size - 1} for x in axis]},
                {"name": "West", "cells": [{"x": 0, "y": y} for y in axis]},
            ]
        else:
            # Custom doors replace all default doors; exit_width no longer defines them.
            require(isinstance(config.exits, list) and len(config.exits) > 0,
                    "Provide at least one exit.")
            self.exits = copy.deepcopy(config.exits)
        # Validate door identity and position before marking boundary cells walkable.
        names = set()
        for k, exit_info in enumerate(self.exits):
            require(isinstance(exit_info, dict), "Each exit must be an object.")
            name = exit_info.get("name")
            require(isinstance(name, str) and bool(name) and name not in names,
                    "Exit names must be nonempty and unique.")
            names.add(name)
            cells = exit_info.get("cells")
            require(isinstance(cells, list) and bool(cells), "Every exit needs cells.")
            for cell in cells:
                require(isinstance(cell, dict) and "x" in cell and "y" in cell,
                        "Exit cells require x and y coordinates.")
                x, y = cell["x"], cell["y"]
                integer(x, 0, "Exit x"); integer(y, 0, "Exit y")
                require(x < self.size and y < self.size and
                        ((x in (0, self.size - 1)) != (y in (0, self.size - 1))),
                        "Exit cells must be on boundary walls, excluding corners.")
                index = self.index(x, y)
                require(self.exit_at[index] < 0, "Exit cells cannot overlap.")
                self.exit_at[index] = k
                self.walkable[index] = True
        # Four-neighbor connectivity permits orthogonal movement only: no diagonals.
        # These links describe static floor geometry; occupancy is checked each step.
        self.neighbors = []
        for cell in range(self.cell_count):
            x, y = self.position(cell)
            self.neighbors.append([
                self.index(a, b) for a, b in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y))
                if 0 <= a < self.size and 0 <= b < self.size and self.walkable[self.index(a, b)]
            ])
        # Each field gives unobstructed graph distance to one door, with -1 meaning
        # unreachable. It ignores people; dynamic queues arise in the movement loop.
        self.navigation_fields = [self._distance_field(k) for k in range(len(self.exits))]
        self.spawn_cells = []
        for cell in range(self.cell_count):
            if self.walkable[cell] and self.exit_at[cell] < 0:
                # Nobody may spawn on a door or in a region lacking an exit route.
                require(any(f[cell] >= 0 for f in self.navigation_fields),
                        "An interior region has no reachable exit.")
                self.spawn_cells.append(cell)

    def index(self, x: int, y: int) -> int:
        return y * self.size + x

    def position(self, cell: int) -> tuple[int, int]:
        return cell % self.size, cell // self.size

    def _distance_field(self, exit_id: int) -> list[int]:
        # Breadth-first search expands backward from every cell of this door.
        # Equal-cost links make first arrival the shortest number of movement steps.
        result = [-1] * self.cell_count
        queue = deque(self.index(c["x"], c["y"]) for c in self.exits[exit_id]["cells"])
        for cell in queue:
            result[cell] = 0
        while queue:
            cell = queue.popleft()
            for neighbor in self.neighbors[cell]:
                if result[neighbor] < 0 and self.exit_at[neighbor] in (-1, exit_id):
                    # Other doors are terminal destinations, not transit corridors.
                    result[neighbor] = result[cell] + 1
                    queue.append(neighbor)
        return result

    def perceived_distance(self, cell: int, exit_id: int) -> int:
        # Utility uses simple Manhattan proximity, not the obstacle-aware BFS field.
        # The separate movement field assumes navigation assistance around obstacles.
        x, y = self.position(cell)
        return min(abs(x - c["x"]) + abs(y - c["y"]) for c in self.exits[exit_id]["cells"])


@dataclass
class Agent:
    # Identity is fixed; cell changes as the person moves. initial_cell is an
    # abstract starting position, not yet a modeled auditorium seat or row.
    id: int
    initial_cell: int
    cell: int
    # Preference weights and auxiliary parameters are fixed across the whole run.
    weights: dict[str, float]
    beta_distance: float
    beta_congestion: float
    panic_susceptibility: float
    # One signed Gaussian draw per door; only its time envelope changes later.
    panic_by_exit: list[float]
    entrance_exit: int
    # -1 means undecided. This square-room version selects doors directly;
    # intermediate row openings and aisle junctions are not modeled yet.
    target: int = -1
    exited: bool = False
    exit_id: int | None = None
    exit_time: int | None = None
    # wait_steps is cumulative; blocked_steps counts consecutive unsuccessful steps.
    wait_steps: int = 0
    blocked_steps: int = 0
    moves: int = 0
    switches: int = 0
    decisions: int = 0
    last_decision: int | None = None
    # Retain the most recent decision's feature breakdown for inspection, not
    # every past evaluation or every historical position.
    last_evaluation: list[dict[str, Any]] | None = None


@dataclass
class Observation:
    # counts is indexed by door. targets freezes previous commitments for all
    # agents, even while their live Agent.target fields are updated sequentially.
    counts: list[int]
    neighbors: list[Agent]
    targets: list[int]


class Simulation:
    def __init__(self, config: SimulationConfig | Mapping[str, Any] | None = None):
        # Normalize inputs to an independent configuration before building state.
        if config is None:
            config = SimulationConfig()
        elif isinstance(config, Mapping):
            config = SimulationConfig.from_dict(config)
        require(isinstance(config, SimulationConfig), "Expected SimulationConfig or a mapping.")
        self.config = copy.deepcopy(config)
        self.config.validate()
        c = self.config
        self.building = Building(c.geometry)
        require(c.participants <= len(self.building.spawn_cells),
                f"Room has {len(self.building.spawn_cells)} initial places; increase geometry.size for {c.participants} participants.")
        self.rng = Random(c.seed)
        # Shuffled unique cells give random initial positions without overlap.
        cells = self.rng.shuffle(self.building.spawn_cells.copy())
        self.agents = []
        for i in range(c.participants):
            # N(0.5, 1) by default: negative draws are intentional and reverse a
            # feature's usual preference. Sampling happens once, not every step.
            weights = {name: self.rng.normal(c.weight_mean, c.weight_variance) for name in WEIGHT_NAMES}
            reachable = [k for k, f in enumerate(self.building.navigation_fields) if f[cells[i]] >= 0]
            self.agents.append(Agent(
                id=i, initial_cell=cells[i], cell=cells[i], weights=weights,
                # These bounded parameters are separate from the five normal weights.
                beta_distance=self.rng.uniform(), beta_congestion=2 * self.rng.uniform() - 1,
                panic_susceptibility=self.rng.uniform(),
                panic_by_exit=[self.rng.normal() for _ in self.building.exits],
                # Entry travel is not simulated: choose a remembered entrance directly.
                entrance_exit=self.rng.pick(reachable),
            ))
        self.time = self.conflicts = self.friction_events = 0
        self.exit_counts = [0] * len(self.building.exits)
        # History stores aggregate time series; exited agents remain in agents
        # for analysis but are removed from the active occupancy map.
        self.history = [{"time": 0, "exited": 0, "active": c.participants, "conflicts": 0}]
        self.occupancy = self._make_occupancy()

    @property
    def exited_count(self) -> int:
        return sum(self.exit_counts)

    @property
    def complete(self) -> bool:
        return self.exited_count == len(self.agents)

    @property
    def finished(self) -> bool:
        # A stopped run is not necessarily complete: it may have hit max_steps.
        return self.complete or self.time >= self.config.max_steps

    def _make_occupancy(self) -> list[int]:
        # -1 means empty; any other value is the occupying agent's ID/list index.
        result = [-1] * self.building.cell_count
        for agent in self.agents:
            if not agent.exited:
                result[agent.cell] = agent.id
        return result

    def observe(self, agent: Agent, occupancy: list[int], targets: list[int]) -> Observation:
        """OBSERVATION EXTENSION POINT: local radius, no wall occlusion yet."""
        b = self.building
        r = self.config.observation_radius
        px, py = b.position(agent.cell)
        counts, neighbors = [0] * len(b.exits), []
        # Scan a bounding square, then retain only cells inside the Manhattan radius.
        # No line-of-sight test is applied, so walls do not currently hide neighbors.
        for y in range(max(1, py - r), min(b.size - 2, py + r) + 1):
            for x in range(max(1, px - r), min(b.size - 2, px + r) + 1):
                if abs(x - px) + abs(y - py) > r:
                    continue
                agent_id = occupancy[b.index(x, y)]
                if agent_id >= 0 and agent_id != agent.id:
                    neighbors.append(self.agents[agent_id])
                    if targets[agent_id] >= 0:
                        # Uncommitted neighbors count as neighbors, but not peer votes.
                        counts[targets[agent_id]] += 1
        return Observation(counts, neighbors, targets)

    def evaluate(self, agent: Agent, observation: Observation, old_target: int) -> list[dict[str, Any]]:
        """UTILITY EXTENSION POINT: the two reference images, operationalized."""
        b, c, w = self.building, self.config, agent.weights
        # Reachability uses simulator knowledge. Available choices are exits,
        # and the agent does not perform global congestion optimization.
        available = [k for k, f in enumerate(b.navigation_fields) if f[agent.cell] >= 0]
        distances = [b.perceived_distance(agent.cell, k) for k in range(len(b.exits))]
        dmin = min(distances[k] for k in available)
        counts = [observation.counts[k] for k in available]
        nmin, nmax, known = min(counts), max(counts), sum(counts)
        evaluations = []
        for k in available:
            # Normalize locally observed commitments across available exits.
            # Equal counts provide no ranking, so all congestion scores become 1.
            crowd = 0 if nmax == nmin else (observation.counts[k] - nmin) / (nmax - nmin)
            if nmax == nmin:
                congestion = 1.0
            elif agent.beta_congestion >= 0:
                # With positive utility, this branch favors MORE crowded exits.
                congestion = crowd ** agent.beta_congestion
            else:
                # This branch favors LESS crowded exits. The sign is deliberate
                # and follows the supplied congestion formula.
                congestion = (1 - crowd) ** (-agent.beta_congestion)
            # The closest exit scores 1; farther exits score no more than 1.
            # Adding one prevents division by zero at a destination.
            distance = ((dmin + 1) / (distances[k] + 1)) ** agent.beta_distance
            # Visible commitments / door width is only a waiting-time proxy,
            # not knowledge of the true global queue or future arrival time.
            time = (distances[k] + observation.counts[k] / len(b.exits[k]["cells"])) / c.time_reference
            # Familiarity is binary; peer share is zero when nobody has committed.
            habit = int(agent.entrance_exit == k)
            peer = observation.counts[k] / known if known else 0
            # Courtesy is represented by a potential queue-conflict proxy. This
            # does not implement literal cutting, queue seniority, or voluntary yielding.
            waiting_ahead = sum(
                other.wait_steps > agent.wait_steps and
                b.perceived_distance(other.cell, k) < distances[k] and observation.targets[other.id] == k
                for other in observation.neighbors
            )
            norm = waiting_ahead / len(observation.neighbors) if observation.neighbors else 0
            switching = int(old_target >= 0 and old_target != k)
            # Dot product of fixed weights with signed action features:
            # (-time, habit, peer, -norm, -switching).
            behavioral = (-w["time"] * time + w["habit"] * habit + w["peer"] * peer
                          - w["norm"] * norm - w["switching"] * switching)
            # Panic is action-specific so it can affect rankings. Its signed draw
            # stays fixed while the envelope grows from zero toward one.
            # It changes preferences only; it does not change movement speed.
            panic = (agent.panic_susceptibility * agent.panic_by_exit[k]
                     * (1 - math.exp(-self.time / c.panic_time_scale)))
            # Fresh decision noise is sampled per evaluated door, per decision.
            # normal() expects variance, so square the configured standard deviation.
            residual = self.rng.normal(0, c.residual_std ** 2)
            evaluations.append({
                "exit": k,
                "utility": (c.distance_scale * distance + c.congestion_scale * congestion
                            + behavioral + c.panic_scale * panic + residual),
                "features": dict(distance=distance, congestion=congestion, time=time, habit=habit,
                                 peer=peer, norm=norm, switching=switching, behavioral=behavioral,
                                 panic=panic, residual=residual),
            })
        return evaluations

    def step(self) -> bool:
        # One call advances one abstract time unit. Repeated calls after termination
        # are harmless and return False without changing state.
        if self.finished:
            return False
        b, c = self.building, self.config
        occupancy = self.occupancy
        targets = [a.target for a in self.agents]
        # All decisions observe the same pre-movement positions and old targets.
        for agent in self.agents:
            if agent.exited:
                continue
            # Keep commitments while progressing. Only initial or sufficiently
            # blocked decisions are revisited, which limits direction oscillation.
            reconsider = agent.target < 0 or (
                agent.blocked_steps >= c.reconsider_after and
                (agent.last_decision is None or self.time - agent.last_decision >= c.reconsider_every))
            if reconsider:
                evaluations = self.evaluate(agent, self.observe(agent, occupancy, targets), targets[agent.id])
                best = max(e["utility"] for e in evaluations)
                # Near-exact ties are randomized; list order does not select a door.
                chosen = self.rng.pick([e for e in evaluations if abs(e["utility"] - best) < 1e-12])
                if self.rng.uniform() < c.exploration_probability:
                    # Explicit exploration is additional to Gaussian residual noise.
                    chosen = self.rng.pick(evaluations)
                if agent.target >= 0 and agent.target != chosen["exit"]:
                    agent.switches += 1
                agent.target = chosen["exit"]
                agent.last_decision = self.time
                agent.decisions += 1
                agent.last_evaluation = evaluations
        # MOVEMENT EXTENSION POINT: request, resolve, and commit simultaneously.
        requests: dict[int, list[int]] = {}
        # Nobody moves yet: every request checks the same original occupancy map.
        # A cell vacated this step still cannot be entered until the next step.
        for agent in self.agents:
            if agent.exited:
                continue
            navigation = b.navigation_fields[agent.target]
            # Only empty neighbors strictly closer along the navigation field qualify.
            # Lateral detours and swapping occupied cells are not allowed here,
            # so dense opposing flows can remain blocked until targets change.
            choices = [n for n in b.neighbors[agent.cell]
                       if occupancy[n] < 0 and 0 <= navigation[n] < navigation[agent.cell]
                       and b.exit_at[n] in (-1, agent.target)]
            if choices:
                minimum = min(navigation[n] for n in choices)
                next_cell = self.rng.pick([n for n in choices if navigation[n] == minimum])
                # Group requests by destination so each cell admits at most one person.
                requests.setdefault(next_cell, []).append(agent.id)
        moves = []
        tick_conflicts = 0
        for cell, contenders in requests.items():
            if len(contenders) > 1:
                tick_conflicts += 1
                if self.rng.uniform() < c.conflict_friction:
                    # A friction event wastes this contested opportunity for everyone.
                    self.friction_events += 1
                    continue
            # Winning is a physical interaction rule, independent of private utility.
            moves.append((self.rng.pick(contenders), cell))
        moved = set()
        # Commit the already-resolved requests. No new requests arise during updates.
        for agent_id, cell in moves:
            agent = self.agents[agent_id]
            agent.cell = cell
            agent.moves += 1
            agent.blocked_steps = 0
            moved.add(agent_id)
            if b.exit_at[cell] >= 0:
                # Door arrival counts at the END of the current step. Multiple
                # cells in a door permit correspondingly greater per-step throughput.
                agent.exited = True
                agent.exit_id = b.exit_at[cell]
                agent.exit_time = self.time + 1
                self.exit_counts[agent.exit_id] += 1
        # Every active person's elapsed step is exactly one move or one wait.
        for agent in self.agents:
            if not agent.exited and agent.id not in moved:
                agent.wait_steps += 1
                agent.blocked_steps += 1
        self.time += 1
        self.conflicts += tick_conflicts
        self.occupancy = self._make_occupancy()
        self.history.append({"time": self.time, "exited": self.exited_count,
                             "active": len(self.agents) - self.exited_count, "conflicts": tick_conflicts})
        return True

    def run(self) -> dict[str, Any]:
        # Headless execution uses the same step() function as the animation.
        while not self.finished:
            self.step()
        return self.summary()

    def summary(self) -> dict[str, Any]:
        # Exit-time statistics include exited participants only. Waiting statistics
        # include everyone, including people still inside at a step limit.
        times = sorted(a.exit_time for a in self.agents if a.exited)
        waits = [a.wait_steps for a in self.agents]
        return {
            "status": "complete" if self.complete else "step_limit" if self.finished else "running",
            "participants": len(self.agents), "exited": self.exited_count,
            "remaining": len(self.agents) - self.exited_count, "elapsedSteps": self.time,
            # Never label a time limit as successful clearance.
            "clearanceTime": self.time if self.complete else None,
            "meanExitTimeAmongExited": sum(times) / len(times) if times else None,
            "p95ExitTimeAmongExited": times[math.ceil(0.95 * len(times)) - 1] if times else None,
            "meanWaitingStepsAllParticipants": sum(waits) / len(waits) if waits else None,
            "switches": sum(a.switches for a in self.agents), "conflicts": self.conflicts,
            "frictionEvents": self.friction_events,
            "exitCounts": {e["name"]: self.exit_counts[k] for k, e in enumerate(self.building.exits)},
        }

    def export(self) -> dict[str, Any]:
        """A detached, strict-JSON-compatible snapshot; no position history."""
        # Deep copies and asdict() let callers edit exports without changing the run.
        return {"version": 1, "implementation": "python", "config": self.config.to_dict(),
                "summary": self.summary(), "history": copy.deepcopy(self.history),
                "agents": [asdict(a) for a in self.agents]}


def recommended_size(participants: int, occupancy_fraction: float = 0.3) -> int:
    """Square side for <= 30% interior occupancy; obstacles need extra space."""
    integer(participants, 0, "Participants")
    require(math.isfinite(occupancy_fraction) and 0 < occupancy_fraction <= 1,
            "Occupancy fraction must lie in (0, 1].")
    # Add two boundary walls to the required interior side length; choose an odd
    # side so centered single-cell doors align with a central row/column.
    # This is a CLI convenience. Set size explicitly to compare populations in
    # a fixed room, and allow extra floor area when adding obstacles.
    size = max(31, math.ceil(math.sqrt(participants / occupancy_fraction)) + 2)
    return size if size % 2 else size + 1
