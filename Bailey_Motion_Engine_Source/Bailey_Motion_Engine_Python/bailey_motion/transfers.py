"""Named portal-to-entrance transfers and separated FIFO stair lanes.

Floor plans have independent body indexes. A person is in transit between them,
keeps its identity/preferences, and can reappear only at its declared entrance.
Stair flights are timed lane queues, not continuous stair-body/contact dynamics.
"""
import math

from . import plans
from .records import Record, record


def initialize(engine):
    for p in engine.portals:
        if not p.evacuationAllowed:
            p.enabled = False
        if p.type in ("stairs", "access"):
            p.lanes = [Record(index=i, agents=[], nextEntryAt=0., lastScheduledFinish=0.)
                       for i in range(p.laneCount)]
    engine.transfer_events = []
    engine.threshold_events = []


def _landing(engine, agent, portal, lane_index=0):
    entry = engine.g.entrances[portal.toEntrance]
    normal = entry.normal
    lane_width = (portal.width - portal.get("laneDivider", 0)) / portal.get("laneCount", 1)
    offset = (lane_index - (portal.get("laneCount", 1) - 1) / 2) * lane_width
    for depth in (0, .25, .5, .75):
        x = entry.x - normal.y * offset + normal.x * depth
        y = entry.y + normal.x * offset + normal.y * depth
        trial = Record(agent, floor=entry.floor, region=entry.region, zone=entry.get("zone"),
                       aisleAngle=entry.get("aisleAngle", agent.aisleAngle))
        if engine._clear(trial, x, y, entry.region):
            return entry, x, y
    return None


def _arrive(engine, agent, portal, landing):
    entry, x, y = landing
    previous = agent.get("transit")
    event = Record(agentId=agent.id, sourcePortal=portal.id, destinationEntrance=entry.id,
                   sourcePlan=portal.plan, destinationPlan=entry.plan, arrivalAt=engine.t,
                   lane=previous.lane if previous else None,
                   enteredAt=previous.enteredAt if previous else engine.t)
    if previous:
        event.update(flightsComplete=previous.flightsComplete, flightCompletionTimes=list(previous.flightEnds))
    engine._index_remove(agent)
    agent.update(floor=entry.floor, planId=entry.plan, region=entry.region, zone=entry.get("zone"),
                 x=x, y=y, vx=0, vy=0, stairUntil=None, stairPortal=None, transit=None)
    if entry.get("aisleAngle") is not None:
        agent.aisleAngle = entry.aisleAngle
    agent.transfers.append(record(event))
    engine.transfer_events.append(event)
    engine._index_add(agent)


def use_portal(engine, agent, portal_id):
    p = engine.portal_map.get(portal_id)
    if p is None or not p.enabled or not plans.eligible(agent, p) or p.type == "exit":
        # Final exits are serviced only by the swept threshold-crossing code.
        return False
    if math.hypot(agent.x - p.x, agent.y - p.y) > .65:
        return False
    if p.get("angle") is not None:
        lateral = -(agent.x - p.x) * math.sin(p.angle) + (agent.y - p.y) * math.cos(p.angle)
        if abs(lateral) > p.width / 2 - agent.radius - .01:
            return False
    if engine.config.limits.doorCapacity and p.tokens < 1:
        engine.metrics.portalWaits += 1
        return False
    if p.type == "door":
        landing = _landing(engine, agent, p)
        if landing is None:
            engine.metrics.portalWaits += 1
            return False
        if engine.config.limits.doorCapacity:
            p.tokens -= 1
        p.passed += 1
        _arrive(engine, agent, p, landing)
        engine._call("on_portal", agent, p, engine.context(agent))
        return True
    speed = max(.4, (agent.params.get("speed") or 1.2) * (.7 if p.type == "stairs" else 1))
    headway = max(.35, (2 * agent.radius + .1) / speed)
    capacity = max(1, math.floor(sum(p.flights) / (2 * agent.radius + .1)))
    lane_width = (p.width - p.laneDivider) / p.laneCount
    options = [lane for lane in p.lanes if lane.nextEntryAt <= engine.t and len(lane.agents) < capacity
               and lane_width > 2 * agent.radius + .02]
    if not options:
        engine.metrics.portalWaits += 1
        return False
    lane = min(options, key=lambda lane: (len(lane.agents), lane.nextEntryAt, lane.index))
    ends, elapsed = [], 0.
    for length in p.flights:
        elapsed += length / speed
        ends.append(engine.t + elapsed)
    arrival = max(ends[-1], lane.lastScheduledFinish + headway)
    ends[-1] = arrival
    if engine.config.limits.doorCapacity:
        p.tokens -= 1
    p.passed += 1
    lane.agents.append(agent.id)
    lane.nextEntryAt, lane.lastScheduledFinish = engine.t + headway, arrival
    engine._index_remove(agent)
    agent.transit = Record(portalId=p.id, sourcePlan=p.plan, sourceFloor=p.floor,
                           destinationEntrance=p.toEntrance, destinationPlan=engine.g.entrances[p.toEntrance].plan,
                           lane=lane.index, enteredAt=engine.t, flightEnds=ends, flightsComplete=0,
                           scheduledArrival=arrival, awaitingEntrance=False)
    agent.update(floor=-1, planId="transit", region="stairs", stairPortal=p.id, stairUntil=arrival, vx=0, vy=0)
    engine._call("on_portal", agent, p, engine.context(agent))
    return True


def advance(engine, agent):
    transit = agent.transit
    p = engine.portal_map[transit.portalId]
    lane = p.lanes[transit.lane]
    transit.flightsComplete = sum(engine.t >= end for end in transit.flightEnds)
    if engine.t < transit.scheduledArrival or not lane.agents or lane.agents[0] != agent.id:
        return
    landing = _landing(engine, agent, p, transit.lane)
    if landing is None:
        transit.awaitingEntrance = True
        engine.metrics.portalWaits += 1
        return
    lane.agents.pop(0)
    _arrive(engine, agent, p, landing)
    engine._call("on_stairs_complete", agent, p, engine.context(agent))


def crossings(engine, agent, x, y):
    for p in engine.portals:
        event = plans.crossing(agent, x, y, p)
        if event is not None:
            yield p, event


def clear_motion(engine, agent, x, y):
    # A disabled or capacity-blocked exterior threshold is a closed gate, even
    # if the geometric point on the far side lies in its legal apron.
    events = list(crossings(engine, agent, x, y))
    bounds = engine.g.regions.get(agent.region)
    outside = False
    if bounds is not None:
        if agent.region == "corridor":
            outside = math.hypot(x, y - engine.g.centerY) > bounds.maxR
        elif agent.region == "foyer": outside = y > bounds.maxY
        elif agent.region == "stage-east": outside = x > bounds.maxX
        elif agent.region == "stage-west": outside = x < bounds.minX
    # An endpoint inside the far-side apron must not let a diagonal segment
    # tunnel through a wall beside a doorway rather than through its opening.
    if outside and not events:
        engine.metrics.regionRejections += 1
        return False
    for p, _ in events:
        if not p.enabled or (engine.config.limits.doorCapacity and p.tokens < 1):
            engine.metrics.portalWaits += 1
            return False
    return engine._clear(agent, x, y)


def finalize_crossing(engine, agent, old_x, old_y):
    trial = Record(agent, x=old_x, y=old_y)
    found = list(crossings(engine, trial, agent.x, agent.y))
    if not found:
        return
    p, event = min(found, key=lambda pair: pair[1].fraction)
    if engine.config.limits.doorCapacity:
        p.tokens -= 1
    p.passed += 1
    event.update(agentId=agent.id, time=max(0, engine.t - engine.config.dt) + event.fraction * engine.config.dt)
    engine.threshold_events.append(record(event))
    agent.exitThreshold = record(event)
    engine.exit(agent, p.exitId, crossing=event)
