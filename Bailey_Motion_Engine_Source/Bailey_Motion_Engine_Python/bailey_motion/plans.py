"""Specification-based two-plan topology and metric geometry approximations.

Only first-floor EXTERIOR thresholds finish evacuation. All other portals name
a destination entrance, including same-floor orchestra-to-loge access points.
There are no automatic exits merely because a person leaves the balcony plan.
"""
import math

from . import geometry as G
from .records import Record, record, finite


def active(g):
    return g.get("layoutVersion", 1) >= 2


def plan_id(g, floor):
    return next((p.id for p in g.plans if p.floor == floor), "transit" if floor == -1 else "outside")


def validate(g):
    if not isinstance(g.get("visibilityWalls", []), list):
        raise ValueError("visibilityWalls must be a list of wall segments.")
    for wall in g.get("visibilityWalls", []):
        if not isinstance(wall, dict) or wall.get("floor") not in (0, 1) or any(
                not isinstance(wall.get(end), dict) or any(not finite(wall[end].get(axis)) for axis in ("x", "y"))
                for end in ("start", "end")):
            raise ValueError("Visibility walls need floor 0 or 1 and finite start/end coordinates.")
        if G.distance(wall.start, wall.end) < 1e-8:
            raise ValueError("Visibility walls must have positive length.")
    ids = [p.id for p in g.plans]
    floors = [p.floor for p in g.plans]
    if len(set(ids)) != 2 or set(floors) != {0, 1}:
        raise ValueError("The specified layout needs distinct main (0) and balcony (1) plans.")
    if {s.id: s.capacity for s in g.sections} != {"orchestra": 527, "loge": 486, "balcony": 316}:
        raise ValueError("Seat inventories must be orchestra 527, loge 486, balcony 316; no extra wheelchair units.")
    if len(g.orchestraBarrier.accessAngles) != 6:
        raise ValueError("The orchestra/loge barrier must have six access points.")
    portal_ids = [p.id for p in g.portals]
    if len(set(portal_ids)) != len(portal_ids):
        raise ValueError("Portal identifiers must be unique.")
    for p in g.portals:
        if p.floor not in floors or p.plan != plan_id(g, p.floor):
            raise ValueError(f"Portal {p.id} has an inconsistent source plan/floor.")
        if not finite(p.width) or p.width <= 0:
            raise ValueError(f"Portal {p.id} needs a positive width.")
        if p.type == "exit":
            if p.floor != 0 or p.get("toEntrance") is not None:
                raise ValueError("Final exits must be first-floor exterior thresholds, not inter-plan transfers.")
            n = p.get("normal", {})
            if not math.isclose(math.hypot(n.get("x", 0), n.get("y", 0)), 1, abs_tol=1e-8):
                raise ValueError(f"Exit {p.id} needs a unit outward normal.")
        elif p.type != "elevator":
            if p.get("toEntrance") not in g.entrances:
                raise ValueError(f"Portal {p.id} needs a corresponding named entrance.")
            entry = g.entrances[p.toEntrance]
            expected = None
            if p.type == "access": expected = (0, "aisle", "loge")
            elif p.id.startswith("AUD"): expected = (0, "corridor", None)
            elif p.id in ("F0", "F1", "F2") or p.id.startswith("BACK_"): expected = (0, "foyer", None)
            elif p.id.startswith("STAGE_"): expected = (0, "stage-east" if p.id.endswith("_E") else "stage-west", None)
            if expected is not None and (entry.floor, entry.region, entry.get("zone")) != expected:
                raise ValueError(f"Portal {p.id} must connect to its corresponding specified entrance region.")
        if p.type in ("stairs", "access"):
            if type(p.laneCount) is not int or p.laneCount < 1 or not p.flights or any(v <= 0 for v in p.flights):
                raise ValueError(f"Connector {p.id} needs positive flights and a positive lane count.")
            if (p.width - p.laneDivider) / p.laneCount <= 0:
                raise ValueError(f"Connector {p.id} has no space after its lane divider.")
            if not math.isclose(sum(p.flights), p.length, abs_tol=1e-8):
                raise ValueError(f"Connector {p.id} flight lengths must sum to its traversal length.")
        if p.type == "elevator" and p.evacuationAllowed:
            raise ValueError("The elevator is excluded from evacuation by specification.")
    for name, entry in g.entrances.items():
        if name != entry.id or entry.floor not in floors or entry.plan != plan_id(g, entry.floor):
            raise ValueError(f"Entrance {name} has an inconsistent destination plan.")
        trial = Record(floor=entry.floor, region=entry.region, zone=entry.get("zone"), radius=.2025,
                       aisleAngle=entry.get("aisleAngle"), seat=Record(r=entry.get("r", 0)))
        if not inside_region(trial, entry.x, entry.y, g):
            raise ValueError(f"Entrance {name} is outside its declared destination region.")
    expected = {"access": 6, "auditorium": 9, "foyer": 3, "main": 5, "side": 4, "balcony_stairs": 4}
    actual = dict(access=sum(p.type == "access" for p in g.portals),
                  auditorium=sum(p.id.startswith("AUD") for p in g.portals),
                  foyer=sum(p.id in ("F0", "F1", "F2") for p in g.portals),
                  main=sum(p.type == "exit" and p.exitId == "MAIN" for p in g.portals),
                  side=sum(p.id.startswith("SIDE_") for p in g.portals),
                  balcony_stairs=sum(p.type == "stairs" and p.floor == 1 for p in g.portals))
    if actual != expected:
        raise ValueError(f"Portal inventory does not match the supplied layout: {actual}")
    for p in g.portals:
        if p.id.startswith("BACK_") and (len(p.flights) != 2 or p.laneCount != 2 or p.laneDivider <= 0):
            raise ValueError("Each back staircase needs two flights and two separated lanes.")


def make_portals(g):
    validate(g)
    return record(g.portals)


def eligible(a, portal):
    return (portal.floor == a.floor and portal["from"] == a.region and portal.evacuationAllowed
            and (portal.get("sourceZone") is None or portal.sourceZone == a.get("zone"))
            and (portal.type != "access" or abs(portal.angle - a.aisleAngle) < 1e-6))


def gate_coordinates(portal, x, y):
    dx, dy = x - portal.x, y - portal.y
    normal = portal.normal
    return dx * normal.x + dy * normal.y, -dx * normal.y + dy * normal.x


def _exit_apron(a, x, y, g):
    # A short continuation beyond each opening lets body centers cross its line.
    # Everything else on the external boundary remains a wall.
    for p in g.portals:
        if p.type == "exit" and eligible(a, p):
            outward, lateral = gate_coordinates(p, x, y)
            if -a.radius - .05 <= outward <= .8 and abs(lateral) <= p.width / 2 - a.radius - .01:
                return True
    return False


def inside_region(a, x, y, g):
    margin = a.get("radius", .2025)
    if a.region in ("stairs", "done"):
        return True
    r, theta = G.radius(Record(x=x, y=y), g), G.polar(Record(x=x, y=y), g)
    if a.floor == 0:
        barrier = g.orchestraBarrier
        overlaps = abs(r - barrier.radius) < barrier.width / 2 + margin
        in_opening = any(abs(theta - fraction * math.pi) * r <= barrier.accessWidth / 2 - margin - .01
                         for fraction in barrier.accessAngles)
        if overlaps and not in_opening:
            return False
    if a.region == "row":
        if a.floor != a.seat.floor:
            return False
        lo = a.seat.leftAisle + g.aisleHalfWidth / a.seat.r
        hi = a.seat.rightAisle - g.aisleHalfWidth / a.seat.r
        return abs(r - a.seat.r) < .07 and lo - .012 <= theta <= hi + .012
    if a.region == "aisle":
        zone = g.zones.get(a.get("zone"))
        if zone is None or zone.floor != a.floor or a.get("aisleAngle") is None:
            return False
        lateral = (theta - a.aisleAngle) * r
        return abs(lateral) <= g.aisleHalfWidth - margin - .02 and zone.minR - .08 <= r <= zone.maxR + .03
    bounds = g.regions.get(a.region)
    if bounds is None or bounds.floor != a.floor:
        return False
    if bounds.kind == "annulus":
        inside = bounds.minR <= r <= bounds.maxR and bounds.minAngle * math.pi <= theta <= bounds.maxAngle * math.pi
    else:
        inside = (bounds.minX + margin <= x <= bounds.maxX - margin and
                  bounds.minY + margin <= y <= bounds.maxY - margin)
    return inside or _exit_apron(a, x, y, g)


def crossing(a, x, y, portal):
    """Swept center/line intersection, not a proximity-based exit decision."""
    if portal.type != "exit" or not eligible(a, portal) or a.floor != 0:
        return None
    start, _ = gate_coordinates(portal, a.x, a.y)
    end, _ = gate_coordinates(portal, x, y)
    if not ((start < 0 and end >= 0) or (abs(start) <= 1e-9 and end > 1e-9)):
        return None
    fraction = G.clamp(-start / (end - start), 0, 1)
    px, py = a.x + fraction * (x - a.x), a.y + fraction * (y - a.y)
    _, lateral = gate_coordinates(portal, px, py)
    if abs(lateral) > portal.width / 2 - a.radius - .01:
        return None
    return Record(fraction=fraction, x=px, y=py, portalId=portal.id, plan=portal.plan, floor=portal.floor)


def movement_goal(a, api):
    g, theta, r = api.geometry, api.polar(a), api.radius(a)
    if a.region == "row":
        return api.point(a.seat.r, a.data.rowEndAngle)
    if a.region == "aisle":
        zone = g.zones[a.zone]
        target_r = zone.maxR
        if zone.outerRegion == "access":
            opening = g.orchestraBarrier.accessWidth / 2 - a.radius - .06
            lateral = (theta - a.aisleAngle) * r
            align_r = target_r - .35
            if r > align_r and abs(lateral) > opening:
                # Center before approaching the narrow barrier opening. A direct
                # diagonal from a row end can otherwise run into the wall edge.
                return api.point(align_r, a.aisleAngle + a.data.aisleOffset / align_r)
        return api.point(target_r, a.aisleAngle + a.data.aisleOffset / target_r)
    p = api.portal(a.data.portal)
    if p is None:
        return Record(x=a.x, y=a.y)
    if p.type == "exit":
        final_goal = Record(x=p.x + p.normal.x * .6, y=p.y + p.normal.y * .6)
    else:
        final_goal = Record(x=p.x, y=p.y)
    bounds = g.regions.get(a.region)
    if bounds is not None and bounds.kind == "rectangle" and p.type == "exit":
        outward, lateral = gate_coordinates(p, a.x, a.y)
        opening = max(.02, p.width / 2 - a.radius - .08)
        if abs(lateral) > opening:
            # A changed target can leave a person in another door's apron.
            # Retreat inside the wall before moving sideways toward the new
            # opening; otherwise every diagonal candidate can hit its jamb.
            depth = a.radius + .08
            if outward > -depth + .05:
                return Record(x=a.x - p.normal.x * (outward + depth),
                              y=a.y - p.normal.y * (outward + depth))
            return Record(x=p.x - p.normal.x * depth, y=p.y - p.normal.y * depth)
    if bounds is not None and bounds.kind == "annulus":
        delta = math.atan2(math.sin(p.angle - theta), math.cos(p.angle - theta))
        # Angular tolerance must scale with actual doorway width and body size.
        # A fixed .055 rad tolerance allowed >1 m sideways error at a side door.
        opening = max(.02, p.width / 2 - a.radius - .08)
        aligned = abs(delta) < math.pi / 2 and abs(r * math.sin(delta)) <= opening
        if not aligned:
            # Follow the current legal circulation radius rather than forcing
            # everyone onto one virtual centerline, including opposing flows.
            travel_r = G.clamp(r, bounds.minR + a.radius + .06, bounds.maxR - a.radius - .06)
            # Exceed the policy's .025 m arrival tolerance; a shorter radial
            # waypoint creates a zero-velocity dead zone before angular progress.
            if abs(r - travel_r) > .05:
                return api.point(travel_r, theta)
            return api.point(travel_r, theta + G.clamp(delta, -.065, .065))
    return final_goal


def obstacle_contacts(a, api):
    """Analytic obstacle samples W for the schematic two-plan geometry.

    Distances are measured from the pedestrian centre to the represented
    surface, with normals directed into the walkable domain. These remain
    region/aisle proxies, not a trace of every seat back in the supplied plans.
    Open exterior apertures have no wall across them, regardless of route choice.
    """
    g, r, theta = api.geometry, api.radius(a), api.polar(a)
    erx, ery = math.cos(theta), math.sin(theta)
    etx, ety = -ery, erx
    contacts = []
    def add(name, distance, nx, ny):
        contacts.append(Record(id=name, distance=max(0., distance), normal=Record(x=nx, y=ny)))

    openings = [p for p in api.portals if p.type == "exit" and p.enabled and eligible(a, p)]
    if a.region == "aisle":
        zone = g.zones[a.zone]
        lateral = (theta - a.aisleAngle) * r
        # The old proxy subtracted body radius here; d_iw now consistently
        # means centre-to-surface distance in the manuscript force calculation.
        add("aisle:right", g.aisleHalfWidth - lateral, -etx, -ety)
        add("aisle:left", g.aisleHalfWidth + lateral, etx, ety)
        add("aisle:inner", r - zone.minR, erx, ery)
    elif a.region in g.regions:
        bounds = g.regions[a.region]
        if bounds.kind == "annulus":
            add(a.region + ":inner", r - bounds.minR, erx, ery)
            through_opening = any(abs(math.atan2(math.sin(theta - p.angle), math.cos(theta - p.angle)))
                                  < math.pi / 2 and abs(r * math.sin(theta - p.angle)) <= p.width / 2
                                  for p in openings)
            if not through_opening:
                add(a.region + ":outer", bounds.maxR - r, -erx, -ery)
        else:
            # Normal sign selects which rectangle edge contains each opening.
            for name, distance, nx, ny in (
                    ("west", a.x - bounds.minX, 1, 0),
                    ("east", bounds.maxX - a.x, -1, 0),
                    ("north", a.y - bounds.minY, 0, 1),
                    ("south", bounds.maxY - a.y, 0, -1)):
                through_opening = any(p.normal.x * nx + p.normal.y * ny < -.99 and
                                      abs(gate_coordinates(p, a.x, a.y)[1]) <= p.width / 2
                                      for p in openings)
                if not through_opening:
                    add(a.region + ":" + name, distance, nx, ny)

    if a.floor == 0:
        barrier = g.orchestraBarrier
        in_opening = any(abs(theta - fraction * math.pi) * barrier.radius <= barrier.accessWidth / 2
                         for fraction in barrier.accessAngles)
        if not in_opening:
            direction = 1 if r >= barrier.radius else -1
            add("orchestra:barrier", abs(r - barrier.radius) - barrier.width / 2,
                direction * erx, direction * ery)
    return contacts


def obstacle_acceleration(a, api, settings):
    """Pre-manuscript steering retained only for explicit legacy comparisons."""
    g, r, theta = api.geometry, api.radius(a), api.polar(a)
    erx, ery = math.cos(theta), math.sin(theta)
    etx, ety = -ery, erx
    ax = ay = 0.
    def push(distance, nx, ny):
        nonlocal ax, ay
        magnitude = settings.obstacleStrength * math.exp(-max(0, distance) / max(.05, settings.comfortDistance))
        ax += magnitude * nx
        ay += magnitude * ny
    if a.region == "aisle":
        zone = g.zones[a.zone]
        lateral = (theta - a.aisleAngle) * r
        half = max(.05, g.aisleHalfWidth - a.radius - .02)
        push(half - lateral, -etx, -ety)
        push(half + lateral, etx, ety)
        push(r - zone.minR, erx, ery)
    elif a.region in g.regions:
        bounds = g.regions[a.region]
        p = api.portal(a.data.portal)
        # Do not add an artificial wall force directly across an open selected gate.
        near_gate = p is not None and p.enabled and api.distance(a, p) < 1.8
        if bounds.kind == "annulus":
            push(r - bounds.minR, erx, ery)
            if not (near_gate and p.type == "exit"):
                push(bounds.maxR - r, -erx, -ery)
        else:
            n = p.get("normal") if near_gate and p.type == "exit" else None
            if n is None or n.x >= 0: push(a.x - bounds.minX, 1, 0)
            if n is None or n.x <= 0: push(bounds.maxX - a.x, -1, 0)
            if n is None or n.y >= 0: push(a.y - bounds.minY, 0, 1)
            if n is None or n.y <= 0: push(bounds.maxY - a.y, 0, -1)
    return Record(x=ax, y=ay)
