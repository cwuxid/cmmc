"""Explicit admission-route memory, separate from evacuation route planning.

Recorded routes can be provided by seat label. Otherwise a deterministic path
through the declared reverse portal topology is replayed as an admission record.
This is labeled reconstructed, not presented as measured arrival behavior.
"""
from collections import deque

from .records import Record


def domain(region, zone=None):
    if region in ("rim",): return "loge"
    if region == "balcony-rim": return "balcony"
    if region == "aisle": return zone
    return region


def source(p):
    return domain(p["from"], p.get("sourceZone"))


def destination(p, g):
    e = g.entrances[p.toEntrance]
    return domain(e.region, e.get("zone"))


def memory(a, api):
    settings = api.config.get("arrival", {})
    if not isinstance(settings, dict) or not isinstance(settings.get("routesBySeat", {}), dict):
        raise ValueError("arrival must contain a routesBySeat object.")
    override = settings.get("routesBySeat", {}).get(a.seat.label)
    portals = {p.id: p for p in api.portals}
    eligible = [p for p in api.portals if p.evacuationAllowed]
    if override is not None:
        if not isinstance(override, dict) or not isinstance(override.get("portals"), list):
            raise ValueError("Each recorded arrival route needs a portals list and optional rowSide.")
        path = list(override.get("portals", []))
        if not all(isinstance(identity, str) for identity in path): raise ValueError("Arrival portal IDs must be strings.")
        origin = "recorded"
    else:
        entry = settings.get("defaultEntrance", "M2")
        if entry not in portals or portals[entry].type != "exit":
            raise ValueError("arrival.defaultEntrance must name an exterior exit used in reverse for admission.")
        start, goal = source(portals[entry]), a.seat.section
        # Deterministic admission assignment. No evacuation global-route search
        # or extra random draws are introduced by this initialization step.
        queue = deque([(start, [entry])])
        seen, path = {start}, None
        while queue:
            here, prefix = queue.popleft()
            if here == goal:
                path = prefix
                break
            edges = [p for p in eligible if p.type != "exit" and destination(p, api.geometry) == here]
            edges.sort(key=lambda p: (abs(p.get("angle", a.seat.angle) - a.seat.angle), p.id))
            for p in edges:
                if p.type == "access" and min(abs(p.angle - a.seat.leftAisle), abs(p.angle - a.seat.rightAisle)) > 1e-6:
                    continue
                there = source(p)
                if there not in seen:
                    seen.add(there)
                    queue.append((there, prefix + [p.id]))
        if path is None:
            raise ValueError(f"No admission path from {entry} to seat {a.seat.label}.")
        origin = "reconstructed"
    if not path or any(identity not in portals for identity in path):
        raise ValueError(f"Invalid arrival portal list for seat {a.seat.label}.")
    first = portals[path[0]]
    if first.type != "exit" or not first.evacuationAllowed:
        raise ValueError("An arrival route must begin at an available exterior threshold.")
    here = source(first)
    for identity in path[1:]:
        p = portals[identity]
        if p.type in ("exit", "elevator") or not p.evacuationAllowed or destination(p, api.geometry) != here:
            raise ValueError(f"Disconnected arrival route at {identity} for {a.seat.label}.")
        here = source(p)
    if here != a.seat.section:
        raise ValueError(f"Arrival route does not reach seat section {a.seat.section}.")
    last = portals[path[-1]]
    approach_angle = last.get("angle", a.seat.angle)
    row_side = "ROW_LEFT" if abs(approach_angle - a.seat.leftAisle) <= abs(approach_angle - a.seat.rightAisle) else "ROW_RIGHT"
    if override is not None:
        row_side = override.get("rowSide", row_side)
    if row_side not in ("ROW_LEFT", "ROW_RIGHT"):
        raise ValueError("Arrival rowSide must be ROW_LEFT or ROW_RIGHT.")
    if last.type == "access":
        angle = a.seat.leftAisle if row_side == "ROW_LEFT" else a.seat.rightAisle
        if abs(last.angle - angle) > 1e-6:
            raise ValueError("Arrival access opening must lead to the recorded seat-row side.")
    return Record(source=origin, seatLabel=a.seat.label, portals=path, rowSide=row_side,
                  knownTargets=path + [row_side])
