"""TEST FIXTURE ONLY: pre-removal five-weight policy for archived JS trajectories.

This class is never selected by the simulator, CLI, or GUI. Current runtime
policies use four weights and contain no familiarity utility contribution.
"""
import math
from bailey_motion.user_model import UserModel
from bailey_motion.records import Record, finite
from bailey_motion import plans


class ArchivedUserModel(UserModel):
    def __init__(self, settings=None):
        super().__init__({"weightSigma": 1.2, "weightRho": -.15, **(settings or {})})
        self.settings.familiarBuildingExit = "MAIN"

    def sample_weights(self, api):
            # Joint lognormal sampling: log(w) = -sigma^2/2 + L*z, z~N(0,I).
            # LL^T is the covariance of the LOG weights. This centering gives E[w_j]=1.
            sigma, rho = self.settings.weightSigma, self.settings.weightRho
            if not (sigma > 0 and -.25 < rho < 1):
                # Five equicorrelated components require rho strictly above -1/4.
                raise ValueError("Invalid weightSigma/weightRho")
            if self._cholesky is None or self._cholesky_sigma != sigma or self._cholesky_rho != rho:
                # Reuse the lower-triangular factor until settings change. rho is not
                # the correlation of the final exponentiated weights.
                covariance = [[sigma * sigma * (1 if i == j else rho) for j in range(5)] for i in range(5)]
                lower = [[0.] * 5 for _ in range(5)]
                for i in range(5):
                    for j in range(i + 1):
                        value = covariance[i][j]
                        for k in range(j):
                            value -= lower[i][k] * lower[j][k]
                        lower[i][j] = math.sqrt(max(value, 0)) if i == j else value / lower[j][j]
                self._cholesky = lower
                self._cholesky_sigma, self._cholesky_rho = sigma, rho
            z = [api.normal() for _ in range(5)]
            # Draw all five latent values before multiplying, preserving source draw order.
            weights = Record()
            for i, name in enumerate(("T", "H", "P", "N", "S")):
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
            # Row distances are arc lengths. The nearby side is also the familiarity
            # stand-in because actual entrance trajectories are unavailable.
            a.data.familiarRowSide = "ROW_LEFT" if left_distance <= right_distance else "ROW_RIGHT"
            choices = [Record(id="ROW_LEFT", angle=left, distance=left_distance,
                              habit=int(a.data.familiarRowSide == "ROW_LEFT")),
                       Record(id="ROW_RIGHT", angle=right, distance=right_distance,
                              habit=int(a.data.familiarRowSide == "ROW_RIGHT"))]
            # The source explicitly bypasses utility for this first choice. Preserve it.
            chosen = choices[0] if left_distance <= right_distance else choices[1]
            a.data.side = 1 if chosen.id == "ROW_LEFT" else -1
            a.aisleAngle = chosen.angle
            a.data.rowEndAngle = a.aisleAngle + a.data.side * (api.geometry.aisleHalfWidth / s.r)
            # A small lateral offset places the next waypoint inside the open aisle;
            # it does not introduce a center divider or an enforced two-person queue.
            a.data.aisleOffset = a.data.side * .20
            a.data.rowSideChoice = chosen.id
            if plans.active(api.geometry):
                # Regular foyer egress is familiar; side/stage alternatives remain
                # available with lower familiarity, as requested for the new layout.
                a.data.familiarBuildingExit = self.settings.familiarBuildingExit

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
                habit = option.get("habit", 0)
                peers = self.peer_share(a, api, option.id, kind)
                norms = self.norm_violation(a, api, option)
                switching = int(current_id is not None and option.id != current_id)
                # Fixed person-level weights multiply changing signed action features.
                # Positive time/norm/switching weights penalize those feature values.
                behavioral = (-weights.T * time + weights.H * habit + weights.P * peers
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
                                          distance=distance, estimatedTime=travel, habit=int(not p.rare)))
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
                habit = (int(p.id.startswith("BACK_")) if a.region == "balcony-rim" else
                         int(abs(p.angle - a.aisleAngle) < .23) if a.region == "rim" else 1)
                actions.append(Record(id=p.id, angle=p.get("angle"), x=p.x, y=p.y,
                                      distance=api.distance(a, p) if a.region == "foyer" else self.arc_distance(a, api, p, track),
                                      habit=habit))
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
                    options.append(Record(id="MAIN", angle=exit_info.angle * math.pi, distance=distance,
                                          habit=int(a.data.get("familiarBuildingExit") == "MAIN")))
                else:
                    p = api.portal(exit_info.id)
                    if p is None:
                        continue
                    options.append(Record(id=exit_info.id, angle=p.angle,
                                          distance=g.corridorR * abs(angle - p.angle) + 1.8,
                                          habit=int(a.data.get("familiarBuildingExit") == exit_info.id)))
            chosen = self.choose(a, api, options, "exit", a.data.exitChoice)
            return chosen.id if chosen is not None else None
