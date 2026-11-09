"""Fixed-step mechanics ported from engine.js, without changing the policy.

Motion is sequential in a seeded randomized order. Spatial buckets preserve
JavaScript Set insertion order, which also fixes interaction summation order.
Doors transfer bodies to a tested landing position; stairs are timed transfers.
"""
from __future__ import annotations

import copy
import csv
import io
import math
from collections import Counter

from . import geometry as G
from .random import RNG
from .records import Record, record, finite
from . import plans, transfers

HOOK_ALIASES = {
    # Optional callbacks may use Python names or the original JavaScript names.
    "before_tick": "beforeTick", "after_tick": "afterTick", "after_move": "afterMove",
    "on_portal": "onPortal", "on_stairs_complete": "onStairsComplete", "on_exit": "onExit",
}


class Context:
    """Live policy API: properties reflect engine changes during the current tick."""

    def __init__(self, engine, current=None):
        # Context delegates to one live engine; it is not a snapshot of a tick.
        self.engine, self.current = engine, current

    @property
    def t(self): return self.engine.t
    # Time is in seconds; tick is a count; dt is seconds per integration step.
    @property
    def tick(self): return self.engine.tick
    @property
    def dt(self): return self.engine.config.dt
    @property
    def config(self): return self.engine.config
    @property
    def geometry(self): return self.engine.g
    @property
    def agents(self): return self.engine.agents
    @property
    def portals(self): return self.engine.portals
    def random(self): return self.engine.rng.uniform()
    # All policy randomness must use this seeded API for repeatable experiments.
    def normal(self): return self.engine.rng.normal()
    def sample(self, params): return self.engine.rng.sample(params)
    def point(self, r, theta): return G.point(r, theta, self.geometry)
    def polar(self, p): return G.polar(p, self.geometry)
    def radius(self, p): return G.radius(p, self.geometry)
    def distance(self, a, b): return G.distance(a, b)
    def portal(self, portal_id): return self.engine.portal_map.get(portal_id)
    def neighbors(self, agent, range=2.5): return self.engine.neighbors(agent, range)
    def clear(self, agent, x, y, region=None): return self.engine._clear(agent, x, y, region)
    def set_region(self, agent, region, x=None, y=None, extras=None):
        return self.engine.set_region(agent, region, x, y, extras)
    def use_portal(self, agent, portal_id): return self.engine.use_portal(agent, portal_id)
    def exit(self, agent, exit_id="CUSTOM"): return self.engine.exit(agent, exit_id)
    def log(self, message): return self.engine.log(message)
    setRegion = set_region
    usePortal = use_portal


class BaileyEngine:
    def __init__(self, config, policy):
        # Clone world data, but keep the supplied policy object and its hooks.
        self.config, self.policy = record(config), policy
        self.rng = RNG(self.config.seed)
        self.g = self.config.geometry
        self.t, self.tick, self.done = 0.0, 0, 0
        self.events, self.history, self.agents = [], [], []
        self.portals = G.make_portals(self.g)
        # Tokens represent available doorway service, not physical people or cells.
        for p in self.portals:
            p.update(enabled=True, tokens=max(1, p.width * 1.2), passed=0)
        self.plan_layout = plans.active(self.g)
        if self.plan_layout:
            transfers.initialize(self)
        self.portal_map = {p.id: p for p in self.portals}
        self.metrics = Record(blockedMoves=0, portalWaits=0, regionRejections=0, collisionRejections=0)
        # Static seating is constructed first; agents then occupy unique sampled seats.
        self.seats = G.build_seats(self.g)
        # Optional experiment object; no graph/staff/state is built in baseline.
        self.crowd = None
        self.students = None
        self.led = None
        student_mode = self.config.get("studentMode", False)
        if type(student_mode) is not bool:
            raise ValueError("studentMode must be true or false.")
        self._spawn()
        self._rebuild_index()
        for agent in self.agents:
            # The policy attaches preferences, memory, and initial waypoints here.
            self._call("setup", agent, self.context(agent))
        experiment = self.config.get("crowdManagers", {})
        if not isinstance(experiment, dict):
            raise ValueError("crowdManagers must be an object.")
        # Student routing suppresses staff entirely. A separately configured
        # physical closure schedule can still run with zero managers.
        if (not student_mode and experiment.get("enabled", False)) or experiment.get("closures"):
            from .crowd_managers import CrowdSystem
            self.crowd = CrowdSystem(self, managers_enabled=False if student_mode else None)
        if student_mode:
            from .students import StudentRouting
            self.students = StudentRouting(self)
        led_spec = self.config.get("ledStrips", {})
        if not isinstance(led_spec, dict):
            raise ValueError("ledStrips must be an object.")
        if not student_mode and led_spec.get("enabled", False):
            from .led_guidance import LEDGuidance
            self.led = LEDGuidance(self)
        self._push_history()

    def _spawn(self):
        # Retain source clamping for direct engine use. The public UI/CLI rejects
        # populations outside capacity before construction instead of clamping them.
        n = min(len(self.seats), max(1, math.floor(self.config.population)))
        sections = self.g.sections
        total = sum(s.capacity for s in sections)
        quota = [math.floor(n * s.capacity / total) for s in sections]
        # Largest fractional remainders distribute leftover seats proportionally.
        remaining = n - sum(quota)
        ranked = sorted(range(len(sections)), key=lambda i: -(n * sections[i].capacity / total - quota[i]))
        for i in ranked[:remaining]:
            quota[i] += 1
        selection = []
        for j, section in enumerate(sections):
            # Sampling within each section is without replacement; section order
            # fixes ID assignment and the sequence of subsequent random draws.
            seats = [seat for seat in self.seats if seat.section == section.id]
            selection.extend(self.rng.shuffle(seats)[:quota[j]])
        for agent_id, seat in enumerate(selection):
            # Configured parameters (speed, radius, reaction, etc.) are sampled
            # before policy.setup samples the separate behavioral weight vector.
            params = Record((key, self.rng.sample(p)) for key, p in self.config.distributions.items())
            self.agents.append(Record(
                id=agent_id, x=seat.x, y=seat.y, vx=0, vy=0, floor=seat.floor,
                region="row", seat=record(seat), aisleAngle=None, params=params,
                radius=params.get("radius", .2), active=True, exited=False, exitAt=None,
                exitId=None, stairUntil=None, stairPortal=None, blockedTicks=0, data=Record()))
            if plans.active(self.g):
                self.agents[-1].update(planId=plans.plan_id(self.g, seat.floor), originPlan=plans.plan_id(self.g, seat.floor),
                                       zone=seat.section, transfers=[], transit=None, exitThreshold=None)

    def _call(self, hook, *args):
        # Policies may be objects or dictionaries of callables. Missing optional
        # hooks do nothing; the loader checks that decide() exists at the boundary.
        def lookup(name):
            return self.policy.get(name) if isinstance(self.policy, dict) else getattr(self.policy, name, None)
        callback = lookup(hook)
        if not callable(callback):
            callback = lookup(HOOK_ALIASES.get(hook, hook))
        if callable(callback):
            return callback(*args)
        return None

    @staticmethod
    def _key(floor, x, y):
        # Buckets accelerate nearby-body searches; they do not discretize motion.
        return floor, math.floor(x / 1.3), math.floor(y / 1.3)

    def _rebuild_index(self):
        # People on stairs (-1) or outside (-2) are absent from the planar index.
        self.grid = {}
        for agent in self.agents:
            if agent.floor >= 0 and not agent.exited:
                self._index_add(agent)

    def _index_add(self, agent):
        # Insertion-ordered dictionaries reproduce the source's ordered Sets.
        self.grid.setdefault(self._key(agent.floor, agent.x, agent.y), {})[agent.id] = agent

    def _index_remove(self, agent):
        self.grid.get(self._key(agent.floor, agent.x, agent.y), {}).pop(agent.id, None)

    def neighbors(self, agent, range=2.5, x=None, y=None):
        # Search same-floor buckets around the current or trial position, then
        # apply true Euclidean distance. Walls do not occlude these queries.
        # Use a differently named loop variable: range is retained for API fidelity.
        from builtins import range as span
        x = agent.x if x is None else x
        y = agent.y if y is None else y
        i, j = math.floor(x / 1.3), math.floor(y / 1.3)
        n, result = math.ceil(range / 1.3), []
        p = Record(x=x, y=y)
        for u in span(-n, n + 1):
            for v in span(-n, n + 1):
                for other in self.grid.get((agent.floor, i + u, j + v), {}).values():
                    if other.id != agent.id and G.distance(p, other) <= range:
                        result.append(other)
        if self.crowd is not None:
            # Staff are physical stationary neighbours but are not in agents,
            # the audience peer-observation snapshot, or population statistics.
            result.extend(m for m in self.crowd.managers if m.floor == agent.floor and G.distance(p, m) <= range)
        return result

    def _clear(self, agent, x, y, region=None):
        # First check the region's allowed domain, then body-disc overlap.
        # Queries increment rejection metrics even when used to test alternatives.
        region = agent.region if region is None else region
        if self.config.limits.enforceRegions:
            if not G.inside_region(Record(agent, region=region), x, y, self.g):
                self.metrics.regionRejections += 1
                return False
        if self.config.limits.hardCollisions:
            staff_radius = max((m.radius for m in self.crowd.managers), default=0.) if self.crowd else 0.
            for other in self.neighbors(agent, agent.radius + max(.9, staff_radius), x, y):
                if (x - other.x) ** 2 + (y - other.y) ** 2 < (agent.radius + other.radius) ** 2 * 1.005:
                    self.metrics.collisionRejections += 1
                    return False
        return True

    def context(self, agent=None):
        # current identifies the subject of a callback; other agents remain visible.
        return Context(self, agent)

    def set_region(self, agent, region, x=None, y=None, extras=None):
        # A region transition can reposition a body, but only after a successful
        # geometry/collision test. Update the spatial index after committing it.
        x, y = agent.x if x is None else x, agent.y if y is None else y
        extras = extras or {}
        if self.plan_layout and (extras.get("floor", agent.floor) != agent.floor or extras.get("zone", agent.get("zone")) != agent.get("zone")):
            # Floor/zone changes require an explicit source portal and named entrance.
            return False
        if self.plan_layout and region != agent.region:
            allowed = (agent.region == "row" and region == "aisle")
            if agent.region == "aisle":
                zone = self.g.zones[agent.zone]
                allowed = region == zone.outerRegion and zone.outerRegion != "access" and G.radius(agent, self.g) >= zone.maxR - .18
            if not allowed or math.hypot(x - agent.x, y - agent.y) > 1.0:
                return False
        trial = Record(agent)
        trial.update(extras)
        trial.region = region
        if not self._clear(trial, x, y, region):
            return False
        self._index_remove(agent)
        agent.x, agent.y, agent.region = x, y, region
        agent.update(extras)
        self._index_add(agent)
        return True

    def use_portal(self, agent, portal_id):
        if self.plan_layout:
            return transfers.use_portal(self, agent, portal_id)
        # Routing belongs to the policy. This method only services its chosen
        # portal when enabled, reachable, on the correct floor, and near enough.
        p = self.portal_map.get(portal_id)
        if not p or not p.enabled or agent.region != p["from"] or agent.floor != p.floor:
            return False
        if G.distance(agent, p) > .94:
            return False
        if self.config.limits.doorCapacity and p.tokens < 1:
            # No throughput token means the person must wait at the doorway.
            self.metrics.portalWaits += 1
            return False
        destination, new_region = None, None
        if p.type == "door":
            # Preserve the source landing search: try depth/lateral offsets on
            # the destination side instead of integrating a continuous crossing.
            new_region = p.to
            for depth in (0, .35, .70, 1.05):
                for lateral in [f * p.width for f in (0, -.20, .20, -.35, .35)]:
                    if new_region == "corridor":
                        r = 24.66 + depth
                        candidate = G.point(r, p.angle + lateral / r, self.g)
                    else:
                        candidate = Record(x=p.x + lateral, y=max(32.8, p.y + .45) + depth)
                    if self._clear(agent, candidate.x, candidate.y, new_region):
                        destination = candidate
                        break
                if destination is not None:
                    break
            if destination is None:
                # Failed landing tests do not consume a service token.
                self.metrics.portalWaits += 1
                return False
        if self.config.limits.doorCapacity:
            p.tokens -= 1
        p.passed += 1
        if p.type == "exit":
            # Final exits remove the person immediately and record current time.
            self.exit(agent, p.exitId)
            self._call("on_portal", agent, p, self.context(agent))
            return True
        self._index_remove(agent)
        if p.type == "stairs":
            # Stairs are timed transfers, not an occupied staircase simulation.
            # Removing the body from the planar index avoids cross-floor collisions.
            agent.region, agent.floor, agent.stairPortal = "stairs", -1, p.id
            agent.stairUntil = self.t + p.length / max(.4, (agent.params.get("speed") or 1.2) * .7)
            agent.vx = agent.vy = 0
        else:
            # Normal door transitions retain the floor and zero velocity at landing.
            agent.x, agent.y, agent.region = destination.x, destination.y, new_region
            agent.vx = agent.vy = 0
            self._index_add(agent)
        self._call("on_portal", agent, p, self.context(agent))
        return True

    def _finish_stairs(self, agent):
        # Emergency stage stairs lead outside; back stairs land in the foyer.
        p = self.portal_map.get(agent.stairPortal)
        if not p:
            return
        if p.destination == "outside":
            self.exit(agent, p.id)
            return
        x, y = (10.6 if p.id.endswith("_E") else -10.6), 35.3
        trial = Record(agent, floor=0, region="foyer")
        if not self._clear(trial, x, y, "foyer"):
            # Retry next tick if the foyer landing remains occupied or invalid.
            agent.stairUntil += self.config.dt
            return
        agent.floor, agent.region, agent.x, agent.y = 0, "foyer", x, y
        agent.vx = agent.vy = 0
        agent.stairUntil = None
        self._index_add(agent)
        self._call("on_stairs_complete", agent, p, self.context(agent))

    def exit(self, agent, exit_id="CUSTOM", *, crossing=None):
        # Exited records remain available for inspection/export, but stop moving
        # and no longer participate in neighborhood collision queries.
        if agent.exited:
            return
        if self.plan_layout and (crossing is None or crossing.floor != 0 or agent.floor != 0):
            raise ValueError("Completion requires crossing a first-floor exterior exit threshold.")
        self._index_remove(agent)
        agent.active, agent.exited, agent.floor, agent.region = False, True, -2, "done"
        agent.vx = agent.vy = 0
        agent.exitId, agent.exitAt = exit_id, self.t
        if self.plan_layout:
            agent.exitAt = crossing.time
            agent.planId = "outside"
            agent.x, agent.y = crossing.x, crossing.y
        self.done += 1
        self._call("on_exit", agent, self.context(agent))

    def log(self, message):
        # Bounded diagnostic log; entries are not a complete event history.
        self.events.append(Record(time=self.t, message=str(message)))
        if len(self.events) > 150:
            self.events.pop(0)

    def _push_history(self):
        # Keep the latest 2,000 aggregate exit counts, not per-person trajectories.
        self.history.append(Record(t=self.t, exited=self.done))
        if len(self.history) > 2000:
            self.history.pop(0)

    def _move(self, agent, command):
        # Convert the policy's requested velocity (m/s) to displacement for one dt.
        # The engine supplies no desired direction or behavioral objective itself.
        if command is None or command is False:
            return
        vx, vy = float(command.get("vx", 0) or 0), float(command.get("vy", 0) or 0)
        if not finite(vx) or not finite(vy):
            raise ValueError(f"Invalid velocity from model for agent {agent.id}")
        dt = self.config.dt
        dx, dy = vx * dt, vy * dt
        distance = math.hypot(dx, dy)
        if distance > .7:
            # Retained source displacement cap, not a preferred-speed model.
            dx, dy = dx * .7 / distance, dy * .7 / distance
        nx, ny = agent.x + dx, agent.y + dy
        if agent.region == "row":
            # Project onto the seat row's circular track. The tangential component
            # changes angle; radial shortcuts across other seat rows are forbidden.
            theta = G.polar(agent, self.g)
            signed = math.cos(theta) * dy - math.sin(theta) * dx
            desired = theta + signed / agent.seat.r
            lo = agent.seat.leftAisle + self.g.aisleHalfWidth / agent.seat.r
            hi = agent.seat.rightAisle - self.g.aisleHalfWidth / agent.seat.r
            p = G.point(agent.seat.r, G.clamp(desired, lo, hi), self.g)
            nx, ny = p.x, p.y
        clear = (lambda a, x, y: transfers.clear_motion(self, a, x, y)) if self.plan_layout else self._clear
        accepted = clear(agent, nx, ny)
        if not accepted and agent.region != "row":
            # Try a half move and axis-aligned slides. These are integration
            # fallbacks, not new utility choices or alternative route searches.
            for mx, my in ((agent.x + dx * .5, agent.y + dy * .5),
                           (agent.x + dx, agent.y), (agent.x, agent.y + dy)):
                if clear(agent, mx, my):
                    nx, ny, accepted = mx, my, True
                    break
        if accepted:
            # Store realized velocity after constraints, so the next policy call
            # reacts to what actually happened rather than the rejected request.
            self._index_remove(agent)
            ox, oy = agent.x, agent.y
            agent.x, agent.y = nx, ny
            agent.vx, agent.vy = (nx - ox) / dt, (ny - oy) / dt
            self._index_add(agent)
            agent.blockedTicks = 0
            if self.plan_layout:
                transfers.finalize_crossing(self, agent, ox, oy)
        else:
            # Only consecutive rejected moves increment blockedTicks; accepting a
            # zero-displacement request resets it, as in the original engine.
            agent.vx = agent.vy = 0
            agent.blockedTicks += 1
            self.metrics.blockedMoves += 1

    @property
    def finished(self):
        # Completion and a time limit both stop stepping, but summaries distinguish them.
        return self.done == len(self.agents) or self.t >= self.config.limits.maxSeconds

    def step(self):
        if self.finished:
            return
        # Source time is advanced BEFORE callbacks and exits are processed.
        self.t += self.config.dt
        self.tick += 1
        if self.crowd is not None:
            self.crowd.before_tick()
        if self.led is not None:
            self.led.before_tick()
        for p in self.portals:
            if p.enabled:
                # Replenish width-dependent service and cap saved-up capacity.
                p.tokens = min(max(1, p.width * 1.35), p.tokens + p.width * 1.3 * self.config.dt)
        self._call("before_tick", self.context())
        # Current behavior freezes its observation snapshot here; archived
        # behavior caches commitments. Forces/motion below remain sequential.
        order = self.rng.shuffle([a.id for a in self.agents])
        # Moves commit sequentially: later agents can see earlier agents' new
        # state. Randomizing order avoids giving a fixed ID priority every tick.
        for i in order:
            a = self.agents[i]
            if a.exited:
                continue
            if a.region == "stairs":
                if self.plan_layout:
                    transfers.advance(self, a)
                    continue
                # Timed transfers bypass the ordinary policy/movement callbacks.
                if self.t >= a.stairUntil:
                    self._finish_stairs(a)
                continue
            api = self.context(a)
            command = self._call("decide", a, api)
            self._move(a, command)
            # The policy can request region/portal transitions after actual movement.
            if not a.exited or not self.plan_layout:
                self._call("after_move", a, api)
        self._call("after_tick", self.context())
        if self.tick % 10 == 0:
            # Record once per ten ticks, regardless of rendering or playback speed.
            self._push_history()

    def run_steps(self, n):
        # Used by single-step controls, bounded experiments, and reference tests.
        for _ in range(n):
            if self.finished:
                break
            self.step()

    def run(self):
        # Headless mode uses exactly the same step() as desktop playback.
        while not self.finished:
            self.step()
        return self.summary()

    def agents_csv(self, include_weights=False):
        # Default columns reproduce the source CSV. Extra weights are opt-in,
        # making behavioral analysis possible without changing source-format exports.
        columns = ["id", "floor", "region", "section", "row", "block", "seat", "x", "y", "radius",
                   "speed", "sanity", "groupthink", "pack", "norms", "reaction", "exited", "exitId", "exitAt"]
        if include_weights:
            columns += ["wT", "wP", "wN", "wS"]
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(columns)
        def scalar(value):
            # Retain JavaScript-style blanks/nulls and lowercase boolean spelling.
            if value is None:
                return ""
            if type(value) is bool:
                return "true" if value else "false"
            if type(value) is float and value.is_integer():
                return str(int(value))
            return str(value)
        for a in self.agents:
            values = [a.id, a.floor, a.region, a.seat.section, a.seat.row + 1, a.seat.block + 1,
                      a.seat.number, f"{a.x:.3f}", f"{a.y:.3f}", a.radius]
            values += [a.params.get(k) for k in ("speed", "sanity", "groupthink", "pack", "norms", "reaction")]
            values += [a.exited, a.exitId, a.exitAt]
            if include_weights:
                values += [a.data.get("weights", {}).get(k) for k in ("T", "P", "N", "S")]
            writer.writerow([scalar(v) for v in values])
        return output.getvalue().rstrip("\n")

    def summary(self):
        # Exit-time means describe only those who exited. A time-limited run has
        # no clearance time; remainingRegions helps locate persistent blockages.
        times = sorted(a.exitAt for a in self.agents if a.exited)
        result = dict(status="complete" if self.done == len(self.agents) else "time_limit" if self.finished else "running",
                    time=self.t, ticks=self.tick, population=len(self.agents), exited=self.done,
                    remaining=len(self.agents) - self.done,
                    clearanceTime=self.t if self.done == len(self.agents) else None,
                    meanExitTimeAmongExited=sum(times) / len(times) if times else None,
                    exitCounts=dict(Counter(a.exitId for a in self.agents if a.exited)),
                    remainingRegions=dict(Counter(a.region for a in self.agents if not a.exited)),
                    metrics=dict(self.metrics))
        if self.plan_layout:
            result.update(planOccupancy=dict(Counter(a.planId for a in self.agents if not a.exited)),
                          exitThresholdCounts=dict(Counter(a.exitThreshold.portalId for a in self.agents if a.exited)),
                          exitedByOriginPlan=dict(Counter(a.originPlan for a in self.agents if a.exited)),
                          completionRule=self.g.completionRule,
                          clearanceTime=max(times) if self.done == len(self.agents) and times else None)
        if self.students is not None:
            result["studentMode"] = self.students.summary()
        if self.led is not None:
            result["ledStrips"] = self.led.summary()
        return result

    def export(self):
        # Return detached data so editing a saved snapshot cannot mutate a live run.
        result = dict(implementation="bailey-python", config=self.config,
                                  policySettings=getattr(self.policy, "settings", {}),
                                  summary=self.summary(), agents=self.agents, portals=self.portals,
                                  history=self.history, events=self.events)
        if self.plan_layout:
            result.update(transferEvents=self.transfer_events, thresholdEvents=self.threshold_events)
        if self.crowd is not None:
            result["crowdManagers"] = self.crowd.export()
        if self.students is not None:
            result["studentRouting"] = self.students.export()
        if self.led is not None:
            result["ledGuidance"] = self.led.export()
        return copy.deepcopy(result)

    # Aliases make the source API recognizable to policy authors.
    setRegion = set_region
    usePortal = use_portal
    runSteps = run_steps
    agentsCSV = agents_csv
