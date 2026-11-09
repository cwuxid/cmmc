"""Local action selection and observable behavioral features for current plans.

Weights stay fixed. Actions, observations, remembered targets, and queue cues
change. Behavior observations are frozen at the start of each tick; physical
motion remains sequential. No global commitment counts enter this policy.
"""
import math

from . import arrival, geometry as G, perception, plans
from .records import Record, record


def stage(a):
    return f"{a.floor}:{a.region}:{a.get('zone')}"


def unit(dx, dy):
    length = math.hypot(dx, dy)
    return Record(x=dx / length, y=dy / length) if length > 1e-10 else Record(x=0., y=0.)


def behavioral_utility(w, features):
    """The manuscript dot product, exposed independently of other utility terms."""
    return -w.T * features.T + w.P * features.P - w.N * features.N - w.S * features.C


class LocalBehavior:
    def __init__(self, policy):
        self.policy = policy
        self.settings = policy.settings
        self.snapshots, self.grid, self.snapshot_tick = {}, {}, None

    def initialize(self, a, api):
        a.data.arrivalMemory = arrival.memory(a, api)
        a.data.knownTargets = {}
        a.data.targetId, a.data.targetStage, a.data.localAction = None, None, None
        a.data.queueSince, a.data.queueTarget = None, None
        a.data.rowBlockedSince = None
        a.data.nextDecision = 0.
        # Initial facing is an observation convention, not the first exit choice.
        a.data.heading = Record(x=math.cos(a.seat.angle), y=math.sin(a.seat.angle))
        self.set_row_side(a, a.data.arrivalMemory.rowSide, api)

    def set_row_side(self, a, identity, api):
        left = identity == "ROW_LEFT"
        a.data.side = 1 if left else -1
        a.aisleAngle = a.seat.leftAisle if left else a.seat.rightAisle
        a.data.rowEndAngle = a.aisleAngle + a.data.side * api.geometry.aisleHalfWidth / a.seat.r
        a.data.aisleOffset = a.data.side * .20
        a.data.rowSideChoice = identity

    def clear_target(self, a):
        a.data.targetId, a.data.targetStage, a.data.localAction = None, None, None
        a.data.portal, a.data.exitChoice = None, None
        a.data.queueSince, a.data.queueTarget = None, None
        a.data.rowBlockedSince = None
        a.data.nextDecision = 0.

    def action(self, a, api, p):
        bounds = api.geometry.regions.get(a.region)
        distance = api.distance(a, p)
        if bounds is not None and bounds.kind == "annulus":
            delta = math.atan2(math.sin(p.angle - api.polar(a)), math.cos(p.angle - api.polar(a)))
            distance = api.radius(a) * abs(delta) + abs(api.radius(a) - api.radius(p))
        return Record(id=p.id, kind="portal", floor=a.floor, target=Record(x=p.x, y=p.y),
                      angle=p.get("angle"), distance=distance, portalType=p.type, width=p.width)

    def available_actions(self, a, api):
        """One action = next physical target, never an aggregate MAIN route."""
        if a.region == "row":
            result = []
            for identity, angle, sign in (("ROW_LEFT", a.seat.leftAisle, 1), ("ROW_RIGHT", a.seat.rightAisle, -1)):
                end = angle + sign * api.geometry.aisleHalfWidth / a.seat.r
                result.append(Record(id=identity, kind="row", floor=a.floor, angle=end,
                                     target=api.point(a.seat.r, end), distance=abs(end - api.polar(a)) * a.seat.r))
            return result
        if a.region == "aisle" and api.geometry.zones[a.zone].outerRegion != "access":
            r = api.geometry.zones[a.zone].maxR
            return [Record(id=f"AISLE_END:{a.zone}:{a.aisleAngle:.8f}", kind="aisle", floor=a.floor,
                           target=api.point(r, a.aisleAngle + a.data.aisleOffset / r), distance=max(0, r - api.radius(a)))]
        return [self.action(a, api, p) for p in api.portals
                if plans.eligible(a, p) and p.id not in a.data.knownBlocked]

    def perceived_actions(self, a, api):
        result = []
        memory = a.data.arrivalMemory.knownTargets
        actions = self.available_actions(a, api)
        crowd = api.engine.crowd
        instruction = crowd.receive(a, actions, stage(a)) if crowd and crowd.managers else None
        if api.engine.students is not None:
            # Full layout knowledge bypasses target visibility, not closure
            # discovery. Unexpected obstructions must still be learned locally
            # through the ordinary local closure-discovery rule.
            for action in actions: action.perception = "known-layout"
            return [action for action in actions if action.id not in a.data.knownBlocked]
        led = api.engine.led
        led_instruction = led.instruction(a, actions) if led is not None else None
        for action in actions:
            if action.id in a.data.knownBlocked: continue
            seen = perception.visible(a, action.target, api, self.settings)
            remembered = action.id in memory or action.id in a.data.knownTargets or action.id == a.data.targetId
            directed = instruction is not None and instruction.actionId == action.id
            illuminated = led_instruction is not None and led_instruction.actionId == action.id
            # A single aisle continuation is physically constrained, not knowledge
            # of a remote exit. Other unseen, unknown candidates are not offered.
            if seen or remembered or directed or illuminated or action.kind == "aisle":
                action.perception = "led" if illuminated else "guided" if directed else "visible" if seen else "remembered" if remembered else "continuation"
                result.append(action)
                if seen or directed or illuminated: a.data.knownTargets[action.id] = record(action.target)
        if not result and a.region in api.geometry.regions and api.geometry.regions[a.region].kind == "annulus":
            # Search locally when no egress is seen or remembered. These walking
            # targets use region bounds, not the locations of hidden doorways.
            bounds, theta = api.geometry.regions[a.region], api.polar(a)
            radius = G.clamp(api.radius(a), bounds.minR + a.radius + .08, bounds.maxR - a.radius - .08)
            for sign, identity in ((-1, "SEARCH_LEFT"), (1, "SEARCH_RIGHT")):
                angle = G.clamp(theta + sign * .1, bounds.minAngle * math.pi + .01, bounds.maxAngle * math.pi - .01)
                target = api.point(radius, angle)
                if api.distance(a, target) > .1:
                    result.append(Record(id=identity, kind="search", floor=a.floor, target=target,
                                         distance=api.distance(a, target), perception="search"))
        return result

    def goal(self, a, api, action):
        if action.kind == "search": return action.target
        if action.kind == "row":
            return action.target
        trial = Record(a)
        trial.data = Record(a.data)
        if action.kind == "portal": trial.data.portal = action.id
        return plans.movement_goal(trial, api)

    def direction(self, a, api, action):
        goal = self.goal(a, api, action)
        return unit(goal.x - a.x, goal.y - a.y)

    def before_tick(self, api):
        self.snapshots, self.grid = {}, {}
        cell = self.settings.observeRadius
        for a in api.agents:
            if a.exited or a.floor < 0: continue
            action = a.data.get("localAction")
            intent = self.direction(a, api, action) if action is not None else unit(a.vx, a.vy)
            waiting = (action is not None and action.kind == "portal" and a.data.started and
                       api.distance(a, action.target) <= self.settings.queueObservationDistance and
                       math.hypot(a.vx, a.vy) <= self.settings.queueSpeedThreshold)
            if waiting:
                if a.data.queueTarget != action.id or a.data.queueSince is None:
                    a.data.queueTarget, a.data.queueSince = action.id, api.t
            else:
                a.data.queueTarget, a.data.queueSince = None, None
            if a.region == "row" and a.data.started and a.blockedTicks > 0:
                if a.data.rowBlockedSince is None: a.data.rowBlockedSince = api.t
            else:
                a.data.rowBlockedSince = None
            snap = Record(id=a.id, x=a.x, y=a.y, vx=a.vx, vy=a.vy, floor=a.floor, radius=a.radius,
                          region=a.region, zone=a.get("zone"), data=Record(heading=record(a.data.heading)),
                          intent=intent, targetId=action.id if action else None,
                          target=record(action.target) if action else None,
                          queueTarget=a.data.queueTarget, queueSince=a.data.queueSince,
                          seatSection=a.seat.section, seatRow=a.seat.row, seatBlock=a.seat.block,
                          rowBlockedSince=a.data.rowBlockedSince)
            self.snapshots[a.id] = snap
            key = (a.floor, math.floor(a.x / cell), math.floor(a.y / cell))
            self.grid.setdefault(key, []).append(snap)
        self.snapshot_tick = api.tick

    def observed(self, a, api):
        if self.snapshot_tick != api.tick:
            self.before_tick(api)
        subject = self.snapshots.get(a.id, a)
        if subject.floor != a.floor or subject.region != a.region: subject = a
        cell = self.settings.observeRadius
        i, j = math.floor(subject.x / cell), math.floor(subject.y / cell)
        result = []
        for x in range(i - 1, i + 2):
            for y in range(j - 1, j + 2):
                for b in self.grid.get((a.floor, x, y), []):
                    if b.id != a.id and perception.visible(subject, b, api, self.settings, cell):
                        result.append(b)
        return result

    def features(self, a, api, action, observations=None, current_id=None):
        """Shared observation-to-feature rule; weights are applied only afterward."""
        near = self.observed(a, api) if observations is None else observations
        direction = self.direction(a, api, action)
        threshold = math.cos(math.radians(self.settings.peerDirectionToleranceDegrees))
        following = sum(b.intent.x * direction.x + b.intent.y * direction.y >= threshold for b in near)
        peers = following / len(near) if near else 0.
        moving = [b for b in near if math.hypot(b.vx, b.vy) > .12]
        opposed = sum((b.vx * direction.x + b.vy * direction.y) / math.hypot(b.vx, b.vy) < -.15 for b in moving)
        counterflow = opposed / len(moving) if moving else 0.
        distance = action.distance
        waiting = [b for b in near if b.queueTarget == action.id and b.queueSince is not None and
                   G.distance(b, action.target) <= self.settings.queueObservationDistance]
        mine = self.snapshots.get(a.id)
        own_since = mine.queueSince if mine is not None and mine.queueTarget == action.id else None
        priority = [b for b in waiting if own_since is None or (b.queueSince, b.id) < (own_since, a.id)]
        cutting = sum(G.distance(b, action.target) > G.distance(a, action.target) + a.radius + b.radius + .05 for b in priority)
        queue_cut = cutting / len(priority) if priority else 0.
        ahead = sum(G.distance(b, action.target) <= G.distance(a, action.target) + a.radius for b in priority)
        wait = ahead / max(.1, action.get("width", 1.) * 1.3) if self.settings.perceivedQueueDelay else 0.
        row_blockers = [b for b in near if action.kind == "row" and b.region == "row" and
                        (b.seatSection, b.seatRow, b.seatBlock) == (a.seat.section, a.seat.row, a.seat.block) and
                        0 < (b.x - a.x) * direction.x + (b.y - a.y) * direction.y < action.distance and
                        b.intent.x * direction.x + b.intent.y * direction.y < -.3]
        row_since = a.data.get("rowBlockedSince")
        row_wait = (self.settings.rowBlockWaitFactor * (max(0., api.t - row_since) + self.settings.decisionInterval)
                    if self.settings.perceivedQueueDelay and row_blockers and row_since is not None else 0.)
        travel = distance / max(.35, a.params.get("speed") or 1.2)
        return Record(T=(travel + wait + row_wait) / self.settings.timeScale,
                      P=peers,
                      N=max(counterflow, queue_cut), C=float(current_id is not None and action.id != current_id),
                      travelSeconds=travel, queueSeconds=wait, observedPeople=len(near),
                      rowBlockedSeconds=row_wait, rowBlockers=len(row_blockers),
                      queuePeopleAhead=ahead, counterflow=counterflow, queueCut=queue_cut)

    def choose(self, a, api, options, kind="portal", current_id=None):
        if api.engine.students is not None:
            return api.engine.students.choose(a, api, options, current_id)
        if not options: return None
        observations = self.observed(a, api)
        minimum = min(o.distance for o in options)
        scores, winner, best = [], None, -math.inf
        w = a.data.weights
        crowd = api.engine.crowd
        led = api.engine.led
        for action in options:
            f = self.features(a, api, action, observations, current_id)
            behavioral = behavioral_utility(w, f)
            distance = ((minimum + 1) / (action.distance + 1)) ** a.data.betaDistance
            panic = 0. if self.settings.behavioralOnly else a.data.panicSensitivity * (1 - math.exp(-api.t / 60)) * self.policy.shock(a, api, action.id, "panic")
            residual = 0. if self.settings.behavioralOnly else self.policy.shock(a, api, action.id, "residual")
            total = behavioral if self.settings.behavioralOnly else distance + behavioral + panic + residual
            bonus = crowd.bonus(a, action) if crowd and crowd.managers else 0.
            led_bonus = led.bonus(a, action) if led is not None else 0.
            total += bonus + led_bonus
            scores.append(Record(id=action.id, kind=action.kind, target=record(action.target),
                                 perception=action.get("perception"), features=f, behavioral=behavioral,
                                 distance=distance, panic=panic, residual=residual, utility=total))
            if crowd and crowd.managers: scores[-1].guidanceBonus = bonus
            if led is not None: scores[-1].ledBonus = led_bonus
            if total > best: winner, best = action, total
        a.data.lastUtility = best
        a.data.lastDecision = Record(time=api.t, stage=stage(a), currentTarget=current_id,
                                     chosen=winner.id, alternatives=scores, globalCrowdTerm=0.)
        if crowd and crowd.managers:
            instruction = a.data.guidance.memory
            a.data.lastDecision.guidance = record(instruction)
            # A local counterfactual over the SAME offered actions: subtract
            # only G, retaining crowd state, information and all random shocks.
            # This diagnoses a bonus changing this choice, not a whole-run
            # causal effect or the effect of newly revealed targets.
            without_bonus = max(scores, key=lambda s: s.utility - s.guidanceBonus).id
            changed = winner.id != without_bonus
            a.data.lastDecision.choiceWithoutGuidanceBonus = without_bonus
            a.data.lastDecision.guidanceChangedChoice = changed
            a.data.guidance.changedChoiceDecisions += int(changed)
            if instruction:
                a.data.guidance.recommendedDecisions += 1
                a.data.guidance.followedDecisions += int(winner.id == instruction.actionId)
        if led is not None:
            instruction = a.data.led.instruction
            without_led = max(scores, key=lambda s: s.utility - s.ledBonus).id
            changed = winner.id != without_led
            a.data.lastDecision.update(led=record(instruction),ledStrength=led.config.strength,
                                      choiceWithoutLEDBonus=without_led,ledChangedChoice=changed)
            a.data.led.changedChoiceDecisions += int(changed)
            if instruction:
                a.data.led.recommendedDecisions += 1
                a.data.led.followedDecisions += int(winner.id == instruction.actionId)
        return winner

    def commit(self, a, api, action):
        old = a.data.targetId
        if action.id != old:
            a.data.queueSince, a.data.queueTarget = None, None
        a.data.localAction = record(action)
        a.data.targetId, a.data.targetStage = action.id, stage(a)
        a.data.portal = action.id if action.kind == "portal" else None
        a.data.exitChoice = None
        if action.kind == "row": self.set_row_side(a, action.id, api)
        a.data.heading = self.direction(a, api, action)
        a.data.nextDecision = api.t + self.settings.decisionInterval

    def decide(self, a, api):
        if api.t < (a.params.get("reaction") or 0): return Record(vx=0., vy=0.)
        a.data.started = True
        closed = False
        for p in api.portals:
            if plans.eligible(a, p) and not p.enabled and p.id not in a.data.knownBlocked and \
                    api.distance(a, p) <= self.settings.discoveryRadius and perception.visible(a, p, api, self.settings):
                a.data.knownBlocked.append(p.id)
                closed = closed or p.id == a.data.targetId or p.id == a.data.portal
        if closed: self.clear_target(a)
        if api.t + 1e-9 >= a.data.nextDecision:
            current = a.data.targetId if a.data.targetStage == stage(a) else None
            options = self.perceived_actions(a, api)
            chosen = self.choose(a, api, options, current_id=current)
            if chosen is None:
                if api.engine.students is not None:
                    # Do not resume a stale route on ticks between decisions
                    # when every known continuation has become unreachable.
                    self.clear_target(a)
                a.data.heading = Record(x=-a.data.heading.y, y=a.data.heading.x)
                a.data.nextDecision = api.t + self.settings.decisionInterval
                return Record(vx=0., vy=0.)
            self.commit(a, api, chosen)
        action = a.data.localAction
        if action is None and api.engine.students is not None:
            return Record(vx=0., vy=0.)
        # A manually held portal request remains usable by mechanics experiments.
        if action is None: return self.policy.compute_velocity(a, api, plans.movement_goal(a, api))
        return self.policy.compute_velocity(a, api, self.goal(a, api, action))

    def after_move(self, a, api):
        if not a.data.started: return
        if a.region == "row":
            if abs(self.policy.angle_difference(api.polar(a), a.data.rowEndAngle)) * a.seat.r > .07: return
            angle = a.aisleAngle + a.data.side * (api.geometry.aisleHalfWidth - a.radius - .06) / a.seat.r
            target = api.point(a.seat.r, angle)
            if api.set_region(a, "aisle", target.x, target.y): self.clear_target(a)
        elif a.region == "aisle":
            zone = api.geometry.zones[a.zone]
            if api.radius(a) < zone.maxR - .16: return
            if zone.outerRegion == "access":
                if a.data.portal: api.use_portal(a, a.data.portal)
            elif api.set_region(a, zone.outerRegion): self.clear_target(a)
        elif a.region in api.geometry.regions and a.data.portal:
            api.use_portal(a, a.data.portal)
