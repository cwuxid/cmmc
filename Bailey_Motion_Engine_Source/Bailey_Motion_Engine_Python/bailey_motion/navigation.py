"""Local, target-preserving collision avoidance for the current two-plan layout.

The force model supplies a requested velocity. If that request predicts a
collision or remains stagnant, sample nearby legal velocities so people can
pass instead of repeatedly having the same move rejected. This is local
steering, not an exit reassignment, position reset, or calibrated crowd law.
"""
import math

from . import geometry as G, plans
from .records import Record


def _safe_step(a, api, vx, vy, neighbors):
    x, y = a.x + vx * api.dt, a.y + vy * api.dt
    if api.config.limits.enforceRegions and not plans.inside_region(a, x, y, api.geometry):
        return False
    # Keep the same exact body exclusion as the mechanics engine.
    if api.config.limits.hardCollisions:
        for b in neighbors:
            if (x - b.x) ** 2 + (y - b.y) ** 2 < (a.radius + b.radius) ** 2 * 1.005:
                return False
    bounds = api.geometry.regions.get(a.region)
    outside = False
    if bounds is not None:
        if a.region == "corridor": outside = math.hypot(x, y - api.geometry.centerY) > bounds.maxR
        elif a.region == "foyer": outside = y > bounds.maxY
        elif a.region == "stage-east": outside = x > bounds.maxX
        elif a.region == "stage-west": outside = x < bounds.minX
    crossings = []
    for p in api.portals:
        if p.type == "exit" and plans.crossing(a, x, y, p) is not None:
            crossings.append(p)
            if not p.enabled or (api.config.limits.doorCapacity and p.tokens < 1):
                return False
    return not outside or bool(crossings)


def _predicted_clear(a, vx, vy, neighbors, horizon, padding):
    for b in neighbors:
        rx, ry = b.x - a.x, b.y - a.y
        ux, uy = vx - b.vx, vy - b.vy
        denominator = ux * ux + uy * uy
        t = G.clamp((rx * ux + ry * uy) / denominator, 0, horizon) if denominator > 1e-12 else 0
        physical = (a.radius + b.radius) * math.sqrt(1.005)
        # At existing close contact, do not make the added comfort padding an
        # impossible constraint that prevents a legal sideways separation.
        buffer = min(padding, max(0, (math.hypot(rx, ry) - physical) * .5))
        if math.hypot(rx - t * ux, ry - t * uy) < physical + buffer - 1e-9:
            return False
    return True


def steer(a, api, waypoint, proposed, neighbors, settings):
    if a.region == "row" or not settings.get("localAvoidance", True):
        return proposed
    dx, dy = waypoint.x - a.x, waypoint.y - a.y
    distance = math.hypot(dx, dy)
    if distance < .025:
        return proposed
    gx, gy = dx / distance, dy / distance
    speed = a.params.get("speed") or 1.2
    horizon = settings.get("avoidanceLookahead", .65)
    padding = settings.get("passingClearance", .04)
    key = f"{a.floor}:{a.region}:{a.get('zone')}"
    nav = a.data.get("navigation")
    if nav is None or nav.regionKey != key:
        nav = a.data.navigation = Record(regionKey=key, anchorX=a.x, anchorY=a.y, anchorAt=api.t,
                                          stalledFor=0., avoidanceSteps=0)
    if math.hypot(a.x - nav.anchorX, a.y - nav.anchorY) >= .12:
        nav.anchorX, nav.anchorY, nav.anchorAt = a.x, a.y, api.t
    nav.stalledFor = max(0, api.t - nav.anchorAt)

    safe = _safe_step(a, api, proposed.vx, proposed.vy, neighbors)
    predicted = _predicted_clear(a, proposed.vx, proposed.vy, neighbors, horizon, padding)
    stalled = nav.stalledFor >= settings.get("progressTimeout", 2.)
    if safe and predicted and not stalled:
        return proposed

    # Detect an opposing goal even when both people have already stopped.
    # A shared pair-ID tie break gives them complementary global passing sides
    # without adding RNG draws or imposing a divider across the whole aisle.
    oncoming = None
    for b in neighbors:
        if b.region != a.region or (b.x - a.x) * gx + (b.y - a.y) * gy < -.05:
            continue
        if math.hypot(b.x - a.x, b.y - a.y) > 2.0:
            continue
        other_goal = plans.movement_goal(b, api)
        bx, by = other_goal.x - b.x, other_goal.y - b.y
        length = math.hypot(bx, by)
        if length > .025 and (bx * gx + by * gy) / length < -.3:
            if oncoming is None or G.distance(a, b) < G.distance(a, oncoming):
                oncoming = b
    passing_side = 1 if oncoming is None or (min(a.id, oncoming.id) + max(a.id, oncoming.id)) % 2 == 0 else -1
    candidates = [(proposed.vx, proposed.vy), (0., 0.)]
    for angle in (0, 20, -20, 40, -40, 65, -65, 90, -90, 120, -120, 180):
        theta = math.radians(angle)
        ux, uy = gx * math.cos(theta) - gy * math.sin(theta), gx * math.sin(theta) + gy * math.cos(theta)
        for fraction in (1., .5):
            magnitude = min(speed * fraction, distance / api.dt)
            candidates.append((ux * magnitude, uy * magnitude))
    best, best_score = (0., 0.), -math.inf
    for vx, vy in candidates:
        if not _safe_step(a, api, vx, vy, neighbors):
            continue
        if not _predicted_clear(a, vx, vy, neighbors, horizon, padding):
            continue
        progress = (vx * gx + vy * gy) / speed
        # Rightward velocity relative to travel; the counterpart sees the
        # opposite global direction, resolving exact head-on symmetry.
        lateral = (vx * gy - vy * gx) / speed
        side_bonus = .4 * passing_side * lateral if oncoming is not None else 0.
        deviation = math.hypot(vx - proposed.vx, vy - proposed.vy) / speed
        score = progress + side_bonus - .035 * deviation
        if score > best_score:
            best, best_score = (vx, vy), score
    nav.avoidanceSteps += 1
    nav.lastVelocity = Record(vx=best[0], vy=best[1])
    return Record(vx=best[0], vy=best[1])
