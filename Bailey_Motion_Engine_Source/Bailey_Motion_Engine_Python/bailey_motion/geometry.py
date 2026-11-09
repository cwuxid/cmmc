"""Shared curved seat inventory and geometry dispatch.

Current plan portals/domains live in plans.py. The original hard-coded formulas
below remain available only for archived JavaScript-port replay. Neither mode
claims that the schematic footprint is an as-built survey.
"""
import math

from .records import Record

PI = math.pi

# World coordinates have the auditorium center at (0, centerY). Angles here
# are radians; world JSON stores several angle lists as multiples of pi.

def polar(p, g):
    return math.atan2(p.y - g.centerY, p.x)


def radius(p, g):
    return math.hypot(p.x, p.y - g.centerY)


def point(r, angle, g):
    return Record(x=r * math.cos(angle), y=g.centerY + r * math.sin(angle))


def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def build_seats(g):
    # Divide each curved section into row/aisle blocks, compute their maximum
    # inventories, then allocate exactly the requested section capacity.
    aisles = [v * PI for v in [.02, *g.aisleAngles, .98]]
    all_seats = []
    for sec in g.sections:
        blocks, total = [], 0
        for row in range(sec.rows):
            r = sec.firstR + row * sec.step
            for block in range(len(aisles) - 1):
                left, right = aisles[block], aisles[block + 1]
                available = r * (right - left) - 2 * g.aisleHalfWidth
                # Arc length minus aisle clearance sets the space for seat centers.
                maximum = max(0, math.floor(available / sec.pitch) + 1)
                if not maximum:
                    continue
                blocks.append(Record(row=row, block=block, r=r, left=left, right=right, max=maximum))
                total += maximum
        if total < sec.capacity:
            raise ValueError(f"Insufficient seat space in {sec.id}: {total} < {sec.capacity}")
        filled = 0
        for b in blocks:
            exact = sec.capacity * b.max / total
            b.n = math.floor(exact)
            b.frac = exact - b.n
            filled += b.n
        # Largest-remainder allocation preserves exact per-section capacities.
        for b in sorted(blocks, key=lambda b: (-b.frac, b.row, b.block))[:sec.capacity - filled]:
            b.n += 1
        count = 0
        for b in blocks:
            lo = b.left + g.aisleHalfWidth / b.r
            hi = b.right - g.aisleHalfWidth / b.r
            for k in range(b.n):
                # Position allocated seats evenly along the legal row segment;
                # a single seat is centered rather than divided by n-1.
                theta = (lo + hi) / 2 if b.n == 1 else lo + (hi - lo) * k / (b.n - 1)
                p = point(b.r, theta, g)
                all_seats.append(Record(
                    **p, angle=theta, r=b.r, section=sec.id, floor=sec.floor,
                    row=b.row, block=b.block, number=k + 1, leftAisle=b.left, rightAisle=b.right,
                    label=f"{sec.id[0].upper()}-{b.row + 1:02d}-{b.block + 1}-{k + 1}"))
                count += 1
        if count != sec.capacity:
            raise ValueError(f"Seat count mismatch for {sec.id}: {count}")
    return all_seats


def make_portals(g):
    from . import plans
    if plans.active(g):
        return plans.make_portals(g)
    # Portals connect named regions. They are not just drawing markers: the
    # engine checks source region/floor, proximity, tokens, and landing clearance.
    portals = []
    for i, theta in enumerate(g.auditoriumDoors):
        p = point(23.25, theta * PI, g)
        portals.append(Record(id=f"AUD{i}", type="door", **{"from": "rim"}, to="corridor",
                              floor=0, **p, angle=theta * PI, width=1.35))
    for i, theta in enumerate(g.foyerDoors):
        p = point(25.6, theta * PI, g)
        portals.append(Record(id=f"F{i}", type="door", **{"from": "corridor"}, to="foyer",
                              floor=0, **p, angle=theta * PI, width=1.65))
    for i in range(5):
        # Five final foyer portals share exitId MAIN while retaining separate
        # doorway service tokens and physical coordinates.
        portals.append(Record(id=f"M{i}", type="exit", **{"from": "foyer"}, floor=0,
                              x=(i - 2) * 2.35, y=41.2, width=1.75, exitId="MAIN"))
    for e in g.exits:
        if e.type != "side":
            continue
        p = point(27, e.angle * PI, g)
        portals.append(Record(id=e.id, type="exit", **{"from": "corridor"}, floor=0,
                              **p, angle=e.angle * PI, width=e.width, exitId=e.id))
    for s in g.stairs:
        # destination distinguishes stairs to the foyer from stairs directly outside.
        p = point(23.15, s.angle * PI, g)
        portals.append(Record(id=s.id, type="stairs", **{"from": "balcony-rim"}, floor=1,
                              **p, angle=s.angle * PI, width=s.width, length=s.length, destination=s.type))
    return portals


def inside_region(a, x, y, g):
    from . import plans
    if plans.active(g):
        return plans.inside_region(a, x, y, g)
    # Test a trial body center. Angular/radial bands constrain curved circulation;
    # aisle width includes a body-radius margin, while row travel stays on its track.
    p = Record(x=x, y=y)
    r, t = radius(p, g), polar(p, g)
    margin = a.get("radius", .2)
    if a.region == "row":
        # Row tolerances allow numerical integration near aisle boundaries, but
        # do not permit moving to another row or walking radially through seats.
        current_radius = a.seat.r
        lo = a.seat.leftAisle + g.aisleHalfWidth / current_radius
        hi = a.seat.rightAisle - g.aisleHalfWidth / current_radius
        return abs(r - current_radius) < .07 and lo - .012 <= t <= hi + .012
    if a.region == "aisle":
        lateral = (t - a.aisleAngle) * r
        upper = g.auditoriumR if a.floor == 0 else g.balconyR
        return abs(lateral) <= g.aisleHalfWidth - margin - .02 and a.seat.r - .08 <= r <= upper + .12
    if a.region == "rim":
        return g.auditoriumR - .18 <= r <= 24.4 and .012 * PI <= t <= .988 * PI
    if a.region == "balcony-rim":
        return g.balconyR - .18 <= r <= 24.5 and .008 * PI <= t <= .992 * PI
    if a.region == "corridor":
        return 24.0 <= r <= 27.65 and .005 * PI <= t <= .995 * PI
    if a.region == "foyer":
        # The foyer is rectangular rather than an annular circulation band.
        return -12.4 <= x <= 12.4 and 32.2 <= y <= 41.65
    return a.region in ("stairs", "done")


# Source-style names also work when translating an existing custom policy.
buildSeats = build_seats
makePortals = make_portals
insideRegion = inside_region
