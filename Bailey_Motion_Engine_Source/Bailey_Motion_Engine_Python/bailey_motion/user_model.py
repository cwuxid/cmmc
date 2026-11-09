"""Ported behavioral policy with explicit manuscript forces for current plans.

This is the file to edit for behavioral or steering changes. The port retains
archived source assumptions only in legacy behavior mode. Current plans use
explicit arrival memory, perceived local actions, and frozen local observations.
The archived layout preserves source forces. Current plans default to the
supplied three-term ODE in social_force.py, followed by optional local steering.
"""
from __future__ import annotations

import math
import hashlib

from .config import default_policy_settings
from .records import Record, record, finite
from . import plans, navigation, social_force, behavior


class UserModel:
    def __init__(self, settings=None):
        # Settings are experimental assumptions, not estimates fitted to observations.
        self.settings = default_policy_settings()
        if settings:
            self.settings.update(record(settings))
        # Older saved settings may contain this removed preference. Do not expose
        # or use it in either runtime behavior mode.
        self.settings.pop("familiarBuildingExit", None)
        if self.settings.behaviorMode not in ("local", "legacy"):
            raise ValueError("behaviorMode must be 'local' or 'legacy'.")
        if not finite(self.settings.rowBlockWaitFactor) or self.settings.rowBlockWaitFactor < 0:
            raise ValueError("rowBlockWaitFactor must be finite and nonnegative.")
        for name in ("perceivedQueueDelay", "behavioralOnly"):
            if type(self.settings[name]) is not bool: raise ValueError(f"{name} must be boolean.")
        for name in ("decisionInterval", "legacyDecisionInterval", "timeScale", "noiseInterval", "visionRange",
                     "observeRadius", "discoveryRadius", "queueObservationDistance", "queueSpeedThreshold"):
            if not finite(self.settings[name]) or self.settings[name] <= 0: raise ValueError(f"Invalid {name}.")
        for name, high in (("fieldOfViewDegrees", 360), ("peerDirectionToleranceDegrees", 90)):
            if not finite(self.settings[name]) or not 0 < self.settings[name] <= high: raise ValueError(f"Invalid {name}.")
        if self.settings.socialForceMode not in ("manuscript", "legacy"):
            raise ValueError("socialForceMode must be 'manuscript' or 'legacy'.")
        for name in ("relaxationTime", "comfortDistance", "obstacleStrength", "interactionLambda",
                     "interactionN", "interactionNPrime", "interactionRange", "maxSpeedFactor"):
            value = self.settings[name]
            positive = name in ("relaxationTime", "comfortDistance", "interactionRange", "maxSpeedFactor")
            if not finite(value) or value < 0 or (positive and value == 0):
                raise ValueError(f"Invalid {name}.")
        if type(self.settings.localAvoidance) is not bool:
            raise ValueError("localAvoidance must be true or false.")
        for name in ("avoidanceLookahead", "passingClearance", "progressTimeout"):
            value = self.settings[name]
            if not finite(value) or value < 0 or (name != "passingClearance" and value == 0):
                raise ValueError(f"Invalid {name}.")
        self._cholesky = None
        # Cache the covariance factor; refresh commitment counts before each tick.
        self._counts = {}
        self.local = behavior.LocalBehavior(self)

    def local_behavior(self, api):
        return plans.active(api.geometry) and self.settings.behaviorMode == "local"

    def decision_interval(self, api):
        return self.settings.decisionInterval if plans.active(api.geometry) else self.settings.legacyDecisionInterval

    @staticmethod
    def clamp(x, lo, hi): return max(lo, min(hi, x))
    @staticmethod
    def length(x, y): return math.hypot(x, y)
    @staticmethod
    def angle_difference(a, b): return math.atan2(math.sin(a - b), math.cos(a - b))
    # Wrapped angular differences choose the short signed rotation, in radians.

    def sample_weights(self, api):
        # Joint lognormal sampling: log(w) = -sigma^2/2 + L*z, z~N(0,I).
        # LL^T is the covariance of the LOG weights. This centering gives E[w_j]=1.
        sigma, rho = self.settings.weightSigma, self.settings.weightRho
        if not (finite(sigma) and finite(rho) and sigma > 0 and -1 / 3 < rho < 1):
            # Four equicorrelated components require rho strictly above -1/3.
            raise ValueError("Invalid weightSigma/weightRho")
        if self._cholesky is None or self._cholesky_sigma != sigma or self._cholesky_rho != rho:
            # Reuse the lower-triangular factor until settings change. rho is not
            # the correlation of the final exponentiated weights.
            covariance = [[sigma * sigma * (1 if i == j else rho) for j in range(4)] for i in range(4)]
            lower = [[0.] * 4 for _ in range(4)]
            for i in range(4):
                for j in range(i + 1):
                    value = covariance[i][j]
                    for k in range(j):
                        value -= lower[i][k] * lower[j][k]
                    lower[i][j] = math.sqrt(max(value, 0)) if i == j else value / lower[j][j]
            self._cholesky = lower
            self._cholesky_sigma, self._cholesky_rho = sigma, rho
        z = [api.normal() for _ in range(4)]
        # Draw the joint four-vector before multiplying by its covariance factor.
        weights = Record()
        for i, name in enumerate(("T", "P", "N", "S")):
            latent = -(sigma * sigma) / 2
            for k in range(i + 1):
                latent += self._cholesky[i][k] * z[k]
            weights[name] = math.exp(latent)
        # Positive, unbounded weights are not normalized to a fixed sum.
        return weights

    def setup(self, a, api):
        # This hook runs once per person after the engine samples speed, radius,
        # reaction delay, and configured traits. Policy-owned memory stays in data.
        if self.manuscript_forces(api):
            # Individual r_i may be supplied through world.distributions without
            # adding draws or changing weight initialization in the default world.
            social_force.comfort_distance(a, self.settings)
        a.data.weights = self.sample_weights(api)
        a.data.betaDistance = self.clamp(a.params.get("sanity", .75), 0, 1)
        # Map the bounded groupthink trait into a signed crowd preference:
        # positive follows crowds, negative prefers less crowded options.
        a.data.betaCrowd = self.clamp(2 * a.params.get("groupthink", .5) - 1, -1, 1)
        panic = a.params.get("panic")
        if panic is None:
            # A configured panic parameter takes precedence; otherwise sample it here.
            panic = api.sample(dict(type="beta", mean=self.settings.panicMean, sd=self.settings.panicSD))
        a.data.panicSensitivity = self.clamp(panic, 0, 1)
        a.data.noiseCache = Record()
        # Closed doors become known only through local discovery later in the run.
        a.data.knownBlocked = []
        a.data.portal = a.data.exitChoice = None
        a.data.started, a.data.nextDecision = False, 0
        if self.local_behavior(api):
            self.local.initialize(a, api)
            return
        s = a.seat
        left, right = s.leftAisle, s.rightAisle
        left_distance, right_distance = s.r * (s.angle - left), s.r * (right - s.angle)
        # Legacy routing retains its distance-based row choice without any
        # familiarity feature or reward.
        choices = [Record(id="ROW_LEFT", angle=left, distance=left_distance),
                   Record(id="ROW_RIGHT", angle=right, distance=right_distance)]
        # The source explicitly bypasses utility for this first choice. Preserve it.
        chosen = choices[0] if left_distance <= right_distance else choices[1]
        a.data.side = 1 if chosen.id == "ROW_LEFT" else -1
        a.aisleAngle = chosen.angle
        a.data.rowEndAngle = a.aisleAngle + a.data.side * (api.geometry.aisleHalfWidth / s.r)
        # A small lateral offset places the next waypoint inside the open aisle;
        # it does not introduce a center divider or an enforced two-person queue.
        a.data.aisleOffset = a.data.side * .20
        a.data.rowSideChoice = chosen.id

    def shock(self, a, api, choice_id, kind):
        # Hold each option/kind shock fixed within a noiseInterval time bucket.
        # Re-evaluating the same option in that bucket must not consume new draws.
        bucket = math.floor(api.t / self.settings.noiseInterval)
        key = kind + ":" + choice_id
        old = a.data.noiseCache.get(key)
        if old is not None and old.bucket == bucket:
            return old.value
        if self.settings.get("pairedRandomness", False):
            # Optional experiment-only counter-based normals. Option evaluation
            # order cannot shift another agent's shocks or physical shuffle RNG.
            digest = hashlib.sha256(f"{api.config.seed}:{a.id}:{bucket}:{kind}:{choice_id}".encode()).digest()
            denominator = 2**53 + 1
            u1 = ((int.from_bytes(digest[:8], "big") >> 11) + 1) / denominator
            u2 = ((int.from_bytes(digest[8:16], "big") >> 11) + 1) / denominator
            value = self.settings.shockSD * math.sqrt(-2*math.log(u1)) * math.cos(2*math.pi*u2)
        else:
            value = self.settings.shockSD * api.normal()
        a.data.noiseCache[key] = Record(bucket=bucket, value=value)
        return value

    def before_tick(self, api):
        if self.local_behavior(api):
            self.local.before_tick(api)
            return
        # Population-wide counts of previous commitments. These are global, even
        # though peer_share below uses local neighbors. Stairs count until exit.
        counts = {}
        for a in api.agents:
            if not a.exited:
                for key in (a.data.exitChoice, a.data.portal, a.data.rowSideChoice):
                    if key:
                        counts[key] = counts.get(key, 0) + 1
        self._counts = counts

    def peer_share(self, a, api, choice_id, kind):
        # Local same-floor neighbors include uncommitted people in the denominator.
        # Because updates are sequential, their commitments may already change this tick.
        near = api.neighbors(a, self.settings.observeRadius)
        if not near:
            return 0
        following = 0
        for b in near:
            choice = (b.data.exitChoice if kind == "exit" else b.data.rowSideChoice
                      if kind == "row" else b.data.portal)
            if choice == choice_id:
                following += 1
        return following / len(near)

    def norm_violation(self, a, api, choice):
        # Proxy: the fraction of moving neighbors heading against the candidate
        # direction. This is not explicit queue cutting or a complete social-norm rule.
        near = api.neighbors(a, self.settings.observeRadius)
        if not near:
            return 0
        target = (api.point(api.radius(a), choice.angle) if finite(choice.get("angle"))
                  else Record(x=choice.get("x", a.x), y=choice.get("y", a.y)))
        dx, dy = target.x - a.x, target.y - a.y
        length = math.hypot(dx, dy) or 1
        opposed = moving = 0
        for b in near:
            speed = math.hypot(b.vx, b.vy)
            if speed < .12:
                # Stationary neighbors do not define an opposing direction.
                continue
            moving += 1
            if (b.vx * dx + b.vy * dy) / (speed * length) < -.15:
                opposed += 1
        return opposed / moving if moving else 0

    def choose(self, a, api, options, kind, current_id=None):
        if self.local_behavior(api):
            return self.local.choose(a, api, options, kind, current_id)
        # Evaluate local alternatives for the current decision stage. options are
        # doors/stairs or exit routes, not an optimized full-building path graph.
        if not options:
            return None
        min_distance = min(max(0, o.distance) for o in options)
        counts = [self._counts.get(o.id, 0) for o in options]
        min_count, max_count = min(counts), max(counts)
        weights, beta_d, beta_n = a.data.weights, a.data.betaDistance, a.data.betaCrowd
        chosen, best = None, -math.inf
        for i, option in enumerate(options):
            d = max(0, option.distance)
            normalized_count = (counts[i] - min_count) / (max_count - min_count) if max_count > min_count else None
            # Tied counts and a near-zero exponent contribute no crowd reward.
            crowd = 0
            if normalized_count is not None and abs(beta_n) > 1e-8:
                # Increasing crowd count is rewarded for beta_n>0; the complementary
                # count is rewarded for beta_n<0. Preserve this sign convention.
                crowd = normalized_count ** beta_n if beta_n > 0 else (1 - normalized_count) ** (-beta_n)
            estimated_time = option.get("estimatedTime")
            if estimated_time is None:
                estimated_time = d / max(.35, a.params.get("speed") or 1.2)
            # Default perceived time is travel distance / preferred speed. Unless
            # an option provides estimatedTime, it has no explicit queue-delay term.
            time = estimated_time / self.settings.timeScale
            peers = self.peer_share(a, api, option.id, kind)
            norms = self.norm_violation(a, api, option)
            switching = int(current_id is not None and option.id != current_id)
            # Fixed person-level weights multiply changing signed action features.
            # Positive time/norm/switching weights penalize those feature values.
            behavioral = (-weights.T * time + weights.P * peers
                          - weights.N * norms - weights.S * switching)
            distance_score = ((min_distance + 1) / (d + 1)) ** beta_d
            # Panic magnitude grows over a 60-second envelope; option-specific
            # signed shocks can raise or lower utility. Panic does not set speed.
            panic = a.data.panicSensitivity * (1 - math.exp(-api.t / 60)) * self.shock(a, api, option.id, "panic")
            residual = self.shock(a, api, option.id, "residual")
            utility = distance_score + crowd + behavioral + panic + residual
            # Unlike the older square-room model, there is no additional random
            # exploration branch; variability enters through weights and shocks.
            # Strict > preserves first-option tie handling from the source.
            if utility > best:
                best, chosen = utility, option
        a.data.lastUtility = best
        # Store only the winning score for inspection, not a full decision history.
        return chosen

    def arc_distance(self, a, api, portal, track_r):
        # Approximate remaining travel along a circular circulation track.
        return track_r * abs(self.angle_difference(api.polar(a), portal.angle))

    def select_portal(self, a, api):
        if self.local_behavior(api):
            options = self.local.perceived_actions(a, api)
            current = a.data.targetId if a.data.targetStage == behavior.stage(a) else None
            chosen = self.local.choose(a, api, options, current_id=current)
            if chosen is not None:
                self.local.commit(a, api, chosen)
            return chosen.id if chosen is not None and chosen.kind == "portal" else None
        if plans.active(api.geometry):
            options = [p for p in api.portals if plans.eligible(a, p) and p.id not in a.data.knownBlocked]
            bounds = api.geometry.regions.get(a.region)
            actions = []
            for p in options:
                distance = (self.arc_distance(a, api, p, bounds.trackR)
                            if bounds is not None and bounds.kind == "annulus" else api.distance(a, p))
                travel = distance / max(.35, a.params.get("speed") or 1.2)
                if p.type in ("stairs", "access"):
                    travel += p.length / max(.4, (a.params.get("speed") or 1.2) * (.7 if p.type == "stairs" else 1))
                actions.append(Record(id=p.id, angle=p.get("angle"), x=p.x, y=p.y,
                                      distance=distance, estimatedTime=travel))
            chosen = self.choose(a, api, actions, "portal", a.data.portal)
            return chosen.id if chosen is not None else None
        # A region defines the next reachable portal class. Do not remove a closed
        # portal merely because the engine knows it is closed; the agent must learn it.
        if a.region not in ("rim", "balcony-rim", "foyer"):
            return None
        options = [p for p in api.portals if p["from"] == a.region and p.id not in a.data.knownBlocked]
        track = 23.15 if a.region in ("balcony-rim", "rim") else 0
        actions = []
        for p in options:
            actions.append(Record(id=p.id, angle=p.get("angle"), x=p.x, y=p.y,
                                  distance=api.distance(a, p) if a.region == "foyer" else self.arc_distance(a, api, p, track)))
        chosen = self.choose(a, api, actions, "portal", a.data.portal)
        return chosen.id if chosen is not None else None

    def pick_exit(self, a, api):
        if self.local_behavior(api):
            return self.select_portal(a, api)
        # In the corridor, MAIN is a route via a foyer door and then a final door.
        # Other exit alternatives refer directly to side-door portals.
        g, angle = api.geometry, api.polar(a)
        options = []
        for exit_info in g.exits:
            if exit_info.id in a.data.knownBlocked:
                continue
            if exit_info.id == "MAIN":
                foyer = [p for p in api.portals if p["from"] == "corridor" and p.type == "door"
                         and p.id not in a.data.knownBlocked] if plans.active(g) else [
                             p for p in api.portals if p["from"] == "corridor" and p.id not in a.data.knownBlocked]
                if not foyer:
                    continue
                distance = min(g.corridorR * abs(angle - p.angle) for p in foyer) + 7.5
                # Added route lengths are source approximations, not measured paths.
                options.append(Record(id="MAIN", angle=exit_info.angle * math.pi, distance=distance))
            else:
                p = api.portal(exit_info.id)
                if p is None:
                    continue
                options.append(Record(id=exit_info.id, angle=p.angle,
                                      distance=g.corridorR * abs(angle - p.angle) + 1.8))
        chosen = self.choose(a, api, options, "exit", a.data.exitChoice)
        return chosen.id if chosen is not None else None

    def route_from_corridor(self, a, api):
        if self.local_behavior(api):
            a.data.portal = self.select_portal(a, api)
            return
        # Choose an exit route by utility, then pick the nearest foyer entry if MAIN
        # won. That intermediate foyer-entry selection itself is distance-based.
        selected = self.pick_exit(a, api)
        if selected is None:
            a.data.portal = None
            return
        a.data.exitChoice = selected
        if selected == "MAIN":
            entries = [p for p in api.portals if p["from"] == "corridor" and p.id not in a.data.knownBlocked
                       and (not plans.active(api.geometry) or p.type == "door")]
            entries.sort(key=lambda p: self.arc_distance(a, api, p, api.geometry.corridorR))
            a.data.portal = entries[0].id if entries else None
        else:
            a.data.portal = selected
        a.data.nextDecision = api.t + self.decision_interval(api)

    def goal(self, a, api):
        if self.local_behavior(api) and a.data.get("localAction") is not None:
            return self.local.goal(a, api, a.data.localAction)
        if plans.active(api.geometry):
            return plans.movement_goal(a, api)
        # Translate a selected route into a nearby waypoint. Velocity is computed
        # separately, and the engine can still reject the requested movement.
        g, theta, r = api.geometry, api.polar(a), api.radius(a)
        if a.region == "row":
            # Follow the seat-row arc toward the chosen aisle opening.
            return api.point(a.seat.r, a.data.rowEndAngle)
        if a.region == "aisle":
            # Travel outward to this floor's circulation rim with a slight offset.
            target_r = g.auditoriumR if a.floor == 0 else g.balconyR
            return api.point(target_r, a.aisleAngle + a.data.aisleOffset / target_r)
        if a.region in ("rim", "balcony-rim", "corridor"):
            p = api.portal(a.data.portal)
            if p is None:
                return Record(x=a.x, y=a.y)
            track_r = 25.5 if a.region == "corridor" else 23.15
            delta = self.angle_difference(p.angle, theta)
            if abs(delta) <= .055:
                # Once aligned with the doorway, approach it instead of repeatedly
                # returning to the ideal circulation radius.
                return Record(x=p.x, y=p.y)
            if abs(r - track_r) > .22:
                # Return to the legal circulation track before following its arc.
                return api.point(track_r, theta)
            return api.point(track_r, theta + self.clamp(delta, -.065, .065))
        # The foyer uses direct planar waypoints rather than circular circulation.
        if a.region == "foyer":
            p = api.portal(a.data.portal)
            return Record(x=p.x, y=p.y) if p is not None else Record(x=a.x, y=a.y)
        return Record(x=a.x, y=a.y)

    def manuscript_forces(self, api):
        # Archived geometry always retains its JavaScript-reference trajectories.
        return plans.active(api.geometry) and self.settings.socialForceMode == "manuscript"

    def force_components(self, a, api, waypoint, neighbors=None):
        """Evaluate the image's three terms, before navigation or hard mechanics."""
        if neighbors is None:
            neighbors = api.neighbors(a, self.settings.interactionRange)
        return social_force.components(a, waypoint, plans.obstacle_contacts(a, api), neighbors, self.settings)

    def obstacle_acceleration(self, a, api):
        if self.manuscript_forces(api):
            return social_force.obstacle_acceleration(plans.obstacle_contacts(a, api),
                                                     self.settings.obstacleStrength,
                                                     social_force.comfort_distance(a, self.settings))
        if plans.active(api.geometry):
            return plans.obstacle_acceleration(a, api, self.settings)
        # Soft wall avoidance uses analytical distance proxies for each region.
        # The engine's inside_region/body checks enforce the actual hard constraints.
        g, r, theta = api.geometry, api.radius(a), api.polar(a)
        erx, ery = math.cos(theta), math.sin(theta)
        # Radial and tangential unit vectors express pushes in Cartesian coordinates.
        etx, ety = -math.sin(theta), math.cos(theta)
        ax = ay = 0
        strength, r0 = self.settings.obstacleStrength, max(.05, self.settings.comfortDistance)
        def push(distance, nx, ny):
            # Exponential decay limits influence away from a boundary; r0 is a
            # comfort-distance scale, while obstacleStrength sets acceleration scale.
            nonlocal ax, ay
            magnitude = strength * math.exp(-max(0, distance) / r0)
            ax += magnitude * nx
            ay += magnitude * ny
        if a.region == "aisle":
            lateral = self.angle_difference(theta, a.aisleAngle) * r
            clear_half = max(.05, g.aisleHalfWidth - a.radius - .02)
            push(clear_half - lateral, -etx, -ety)
            push(clear_half + lateral, etx, ety)
            push(r - (a.seat.r - .08), erx, ery)
        elif a.region in ("rim", "balcony-rim", "corridor"):
            lower = 24.0 if a.region == "corridor" else g.auditoriumR - .18 if a.region == "rim" else g.balconyR - .18
            upper = 27.65 if a.region == "corridor" else 24.4 if a.region == "rim" else 24.5
            push(r - lower, erx, ery)
            push(upper - r, -erx, -ery)
        elif a.region == "foyer":
            push(a.x + 12.4, 1, 0)
            push(12.4 - a.x, -1, 0)
            push(a.y - 32.2, 0, 1)
            push(41.65 - a.y, 0, -1)
        return Record(x=ax, y=ay)

    def interaction_acceleration(self, a, api, neighbors):
        if self.manuscript_forces(api):
            return social_force.interaction_acceleration(a, neighbors, self.settings.interactionLambda,
                                                        self.settings.interactionN, self.settings.interactionNPrime)
        # Sum direction-sensitive interpersonal accelerations. These soft terms
        # steer movement; hard disc exclusion is handled separately by the engine.
        ax = ay = 0
        lam = self.settings.interactionLambda
        n, n_prime = self.settings.interactionN, self.settings.interactionNPrime
        for b in neighbors:
            x, y = b.x - a.x, b.y - a.y
            d = math.hypot(x, y)
            if d < 1e-8:
                continue
            hx, hy = x / d, y / d
            dx, dy = hx + lam * (a.vx - b.vx), hy + lam * (a.vy - b.vy)
            # Relative velocity modifies the interaction direction. A small floor
            # avoids division by zero when constructing its unit vector.
            direction = max(1e-5, math.hypot(dx, dy))
            ux, uy = dx / direction, dy / direction
            theta = math.atan2(dx * hy - dy * hx, dx * hx + dy * hy)
            # atan2(cross,dot) supplies a signed angle; the perpendicular vector
            # and its sign determine which lateral direction receives a push.
            nx, ny = -uy, ux
            strength = self.settings.interactionStrength * (.75 + .5 * a.params.get("norms", .5))
            # This sampled norms trait is separate from utility weight wN.
            attenuation = math.exp(-d / direction)
            longitudinal = math.exp(-(n_prime * theta * direction) ** 2)
            sideways = math.exp(-(n * theta * direction) ** 2)
            signed = 1 if theta > 0 else -1 if theta < 0 else 0
            ax -= strength * attenuation * (longitudinal * ux + signed * sideways * nx)
            ay -= strength * attenuation * (longitudinal * uy + signed * sideways * ny)
        return Record(x=ax, y=ay)

    def compute_velocity(self, a, api, waypoint):
        if self.manuscript_forces(api):
            return self.compute_social_force_velocity(a, api, waypoint)
        # Relax realized velocity toward preferred motion, add soft accelerations,
        # then integrate once with explicit Euler. The engine checks the result.
        dx, dy = waypoint.x - a.x, waypoint.y - a.y
        length = math.hypot(dx, dy)
        if length < .025:
            # Already sufficiently near the waypoint: request no displacement.
            return Record(vx=0, vy=0)
        speed = a.params.get("speed") or 1.2
        desired_x, desired_y = speed * dx / length, speed * dy / length
        tau = max(.05, self.settings.relaxationTime)
        # tau is the response time in seconds, not a random behavioral weight.
        obstacles = self.obstacle_acceleration(a, api)
        neighbors = api.neighbors(a, self.settings.interactionRange)
        interactions = self.interaction_acceleration(a, api, neighbors)
        ax = (desired_x - a.vx) / tau + obstacles.x + interactions.x
        ay = (desired_y - a.vy) / tau + obstacles.y + interactions.y
        vx, vy = a.vx + api.dt * ax, a.vy + api.dt * ay
        magnitude = math.hypot(vx, vy)
        max_speed = self.settings.maxSpeedFactor * speed
        if magnitude > max_speed:
            # Cap requested speed relative to the individual's preferred speed.
            vx, vy = vx * max_speed / magnitude, vy * max_speed / magnitude
        limit = length / api.dt
        # A second cap prevents overshooting a nearby waypoint in one tick.
        if math.hypot(vx, vy) > limit:
            cap = limit / math.hypot(vx, vy)
            vx, vy = vx * cap, vy * cap
        requested = Record(vx=vx, vy=vy)
        if plans.active(api.geometry):
            return navigation.steer(a, api, waypoint, requested, neighbors, self.settings)
        return requested

    def compute_social_force_velocity(self, a, api, waypoint):
        """Integrate the manuscript ODE, then apply existing movement safeguards.

        The diagnostic distinguishes raw Euler velocity, capped velocity, and
        the final local-steering request. Actual engine motion can still differ
        because of body exclusion, row projection, door capacity, or transfers.
        """
        neighbors = api.neighbors(a, self.settings.interactionRange)
        forces = self.force_components(a, api, waypoint, neighbors)
        raw = social_force.integrate(a, forces.total, api.dt)
        vx, vy = raw.vx, raw.vy
        distance = api.distance(a, waypoint)
        limit = self.settings.maxSpeedFactor * a.params.get("speed", 1.2)
        if distance > social_force.EPSILON:
            limit = min(limit, distance / api.dt)
        magnitude = math.hypot(vx, vy)
        if magnitude > limit:
            vx, vy = vx * limit / magnitude, vy * limit / magnitude
        capped = Record(vx=vx, vy=vy)
        requested = navigation.steer(a, api, waypoint, capped, neighbors, self.settings)
        a.data.socialForce = Record(time=api.t, dt=api.dt, position=Record(x=a.x, y=a.y),
                                   velocityBefore=Record(vx=a.vx, vy=a.vy), waypoint=record(waypoint),
                                   **forces, rawVelocity=raw, cappedVelocity=capped,
                                   requestedVelocity=requested, localAvoidance=self.settings.localAvoidance)
        return requested

    def observe_closures(self, a, api):
        # Discover only the currently selected portal and only within discoveryRadius.
        # This is local closure learning, not global knowledge of disabled doors.
        portal_id = a.data.portal
        p = api.portal(portal_id) if portal_id else None
        if p is None or p.enabled or api.distance(a, p) > self.settings.discoveryRadius or portal_id in a.data.knownBlocked:
            return
        a.data.knownBlocked.append(portal_id)
        if a.region == "corridor":
            self.route_from_corridor(a, api)
        else:
            a.data.portal = self.select_portal(a, api)
        a.data.nextDecision = api.t + self.decision_interval(api)

    def decide(self, a, api):
        if self.local_behavior(api):
            return self.local.decide(a, api)
        # Per-agent callback before motion: reaction delay, closure observation,
        # eligible route reconsideration, waypoint construction, velocity request.
        if api.t < (a.params.get("reaction") or 0):
            return Record(vx=0, vy=0)
        a.data.started = True
        self.observe_closures(a, api)
        if a.region == "corridor" and api.t >= a.data.nextDecision:
            # Periodic reconsideration is implemented in the corridor only.
            self.route_from_corridor(a, api)
        if (a.region in ("rim", "balcony-rim", "foyer") or
                (plans.active(api.geometry) and a.region in ("stage-east", "stage-west"))) and not a.data.portal:
            # Other circulation stages recover a missing target, but do not
            # generally reroute just because blockedTicks has become large.
            a.data.portal = self.select_portal(a, api)
        return self.compute_velocity(a, api, self.goal(a, api))

    def after_move(self, a, api):
        if self.local_behavior(api):
            self.local.after_move(a, api)
            return
        # Use actual constrained position to request stage changes after movement.
        if not a.data.started:
            return
        g = api.geometry
        if a.region == "row":
            # At the row end, request a checked landing just inside the aisle.
            if abs(self.angle_difference(api.polar(a), a.data.rowEndAngle)) * a.seat.r > .07:
                return
            angle = a.aisleAngle + a.data.side * (g.aisleHalfWidth - a.radius - .06) / a.seat.r
            p = api.point(a.seat.r, angle)
            api.set_region(a, "aisle", p.x, p.y)
            return
        if a.region == "aisle":
            if plans.active(g):
                zone = g.zones[a.zone]
                if api.radius(a) < zone.maxR - .16:
                    return
                if zone.outerRegion == "access":
                    if not a.data.portal:
                        a.data.portal = self.select_portal(a, api)
                    if a.data.portal:
                        api.use_portal(a, a.data.portal)
                elif api.set_region(a, zone.outerRegion):
                    a.data.portal = self.select_portal(a, api)
                    a.data.nextDecision = api.t + self.decision_interval(api)
                return
            # Reaching the outer aisle end enables a choice among rim portals.
            limit = g.auditoriumR if a.floor == 0 else g.balconyR
            if api.radius(a) < limit - .16:
                return
            if api.set_region(a, "rim" if a.floor == 0 else "balcony-rim"):
                a.data.portal = self.select_portal(a, api)
                a.data.nextDecision = api.t + self.decision_interval(api)
            return
        if a.region in ("rim", "balcony-rim", "corridor", "foyer", "stage-east", "stage-west") and a.data.portal:
            # The engine decides whether proximity, capacity, and landing clearance
            # permit the chosen portal crossing at this moment.
            api.use_portal(a, a.data.portal)

    def on_portal(self, a, portal, api):
        if self.local_behavior(api):
            self.local.clear_target(a)
            if a.floor >= 0: self.select_portal(a, api)
            return
        # Successful crossings select the next stage's target, not a whole new
        # global shortest path. Stair completion has its own callback below.
        if a.region == "corridor":
            self.route_from_corridor(a, api)
        elif a.region == "foyer":
            a.data.portal = self.select_portal(a, api)

    def on_stairs_complete(self, a, portal, api):
        if self.local_behavior(api):
            self.local.clear_target(a)
            self.select_portal(a, api)
            return
        # New rear stairs arrive in the foyer; stage stairs arrive on the first
        # floor and still need a final threshold crossing. Legacy stage stairs
        # retain their archived direct-exit behavior.
        a.data.portal = self.select_portal(a, api)

    # Optional aliases for users translating callbacks line by line.
    sampleWeights = sample_weights
    beforeTick = before_tick
    afterMove = after_move
    onPortal = on_portal
    onStairsComplete = on_stairs_complete


def create_policy(settings=None):
    """The GUI/CLI's editable Python-policy contract: return an object with decide()."""
    return UserModel(settings)
