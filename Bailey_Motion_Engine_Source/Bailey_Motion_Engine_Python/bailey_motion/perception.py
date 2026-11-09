"""Range/angle-limited observation with schematic wall occlusion.

Visibility walls are observation geometry only. The existing body mechanics
continues to enforce physical regions and portal crossings independently.
"""
import math

from .records import Record


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def segment_blocks(a, b, start, end):
    """Interior ray/segment intersection, including collinear overlap."""
    dx, dy, wx, wy = b.x - a.x, b.y - a.y, end.x - start.x, end.y - start.y
    sx, sy = start.x - a.x, start.y - a.y
    denominator = _cross(dx, dy, wx, wy)
    if abs(denominator) < 1e-10:
        if abs(_cross(sx, sy, dx, dy)) > 1e-8:
            return False
        length2 = dx * dx + dy * dy
        if length2 < 1e-12: return False
        lo = (sx * dx + sy * dy) / length2
        hi = ((end.x - a.x) * dx + (end.y - a.y) * dy) / length2
        return max(min(lo, hi), 1e-7) < min(max(lo, hi), 1 - 1e-7)
    t, u = _cross(sx, sy, wx, wy) / denominator, _cross(sx, sy, dx, dy) / denominator
    return 1e-7 < t < 1 - 1e-7 and -1e-8 <= u <= 1 + 1e-8


def _ring_hits(a, b, radius, center_y):
    dx, dy, x, y = b.x - a.x, b.y - a.y, a.x, a.y - center_y
    aa = dx * dx + dy * dy
    if aa < 1e-12: return []
    bb, cc = 2 * (x * dx + y * dy), x * x + y * y - radius * radius
    disc = bb * bb - 4 * aa * cc
    if disc < 0: return []
    root = math.sqrt(max(0, disc))
    return [math.atan2(y + t * dy, x + t * dx)
            for t in ((-bb - root) / (2 * aa), (-bb + root) / (2 * aa))
            if 1e-7 < t < 1 - 1e-7]


def line_of_sight(a, target, g, portals):
    if target.get("floor", a.floor) != a.floor:
        return False
    for wall in g.get("visibilityWalls", []):
        if wall.floor == a.floor and segment_blocks(a, target, wall.start, wall.end):
            return False
    if a.floor == 0:
        barrier = g.orchestraBarrier
        for radius in (barrier.radius - barrier.width / 2, barrier.radius + barrier.width / 2):
            for theta in _ring_hits(a, target, radius, g.centerY):
                if not 0 <= theta <= math.pi: continue
                if not any(abs(math.atan2(math.sin(theta - q * math.pi), math.cos(theta - q * math.pi)))
                           * radius <= barrier.accessWidth / 2 for q in barrier.accessAngles):
                    return False
        # The corridor's inner wall separates it from the auditorium. Its AUD
        # apertures are projected onto this schematic ring from portal angles.
        radius = g.regions.corridor.minR
        apertures = [p for p in portals if p.id.startswith("AUD") and p.enabled]
        for theta in _ring_hits(a, target, radius, g.centerY):
            if not 0 <= theta <= math.pi: continue
            if not any(abs(math.atan2(math.sin(theta - p.angle), math.cos(theta - p.angle)))
                       * radius <= p.width / 2 for p in apertures):
                return False
        bounds = g.regions.foyer
        edges = ((Record(x=bounds.minX, y=bounds.minY), Record(x=bounds.maxX, y=bounds.minY), "north"),
                 (Record(x=bounds.minX, y=bounds.maxY), Record(x=bounds.maxX, y=bounds.maxY), "south"),
                 (Record(x=bounds.minX, y=bounds.minY), Record(x=bounds.minX, y=bounds.maxY), "west"),
                 (Record(x=bounds.maxX, y=bounds.minY), Record(x=bounds.maxX, y=bounds.maxY), "east"))
        for start, end, side in edges:
            if not segment_blocks(a, target, start, end): continue
            dx, dy = target.x - a.x, target.y - a.y
            t = ((start.y - a.y) / dy if side in ("north", "south") and abs(dy) > 1e-10 else
                 (start.x - a.x) / dx if abs(dx) > 1e-10 else 0.)
            x = a.x + t * dx
            holes = [p for p in portals if p.enabled and
                     ((side == "north" and p.id in ("F0", "F1", "F2")) or
                      (side == "south" and p.id in ("M0", "M1", "M2", "M3", "M4")))]
            if not any(abs(x - p.x) <= p.width / 2 for p in holes): return False
    return True


def visible(a, target, api, settings, distance_limit=None):
    """A stationary person can scan 360 degrees by default; narrower FOV is configurable."""
    dx, dy = target.x - a.x, target.y - a.y
    distance = math.hypot(dx, dy)
    if distance > (settings.visionRange if distance_limit is None else distance_limit) + 1e-8:
        return False
    if distance > 1e-8 and settings.fieldOfViewDegrees < 360:
        hx, hy = a.vx, a.vy
        if math.hypot(hx, hy) < .05:
            heading = a.data.get("heading", {"x": 0., "y": 1.})
            hx, hy = heading["x"], heading["y"]
        length = math.hypot(hx, hy)
        if length > 1e-8 and (hx * dx + hy * dy) / (length * distance) < math.cos(math.radians(settings.fieldOfViewDegrees / 2)) - 1e-9:
            return False
    return line_of_sight(a, target, api.geometry, api.portals)
