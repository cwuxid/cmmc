"""Read-only rendering of the two plans, barrier openings, linked entrances and thresholds."""
import math

from . import geometry as G
from .records import Record


def draw(canvas, engine, floor, selected=None):
    width, height = canvas.winfo_width(), canvas.winfo_height()
    width = width if width > 1 else int(canvas.cget("width"))
    height = height if height > 1 else int(canvas.cget("height"))
    scale, ox, oy = min(width / 69, height / 52), width / 2, 40
    g = engine.g
    def pt(p): return ox + p.x * scale, oy + p.y * scale
    def flat(points): return [v for p in points for v in pt(p)]
    def text(value, x, y, color="#c4d9e7", size=8, tag="static"):
        canvas.create_text(x, y, text=value, fill=color, anchor="w", font=("Segoe UI", size), tags=tag)
    def arc(r, lo, hi):
        n = max(2, math.ceil(abs(hi - lo) * r * scale / 6))
        return [G.point(r, lo + (hi - lo) * k / n, g) for k in range(n + 1)]
    def band(r0, r1, lo, hi, color):
        canvas.create_polygon(*flat(arc(r1, lo, hi) + arc(r0, hi, lo)), fill=color, outline="", tags="static")
    def line(points, color, width=1, tag="static", **kwargs):
        canvas.create_line(*flat(points), fill=color, width=width, tags=tag, **kwargs)
    key = (id(engine), width, height, floor)
    if getattr(canvas, "_bailey_geometry_key", None) != key:
        canvas.delete("all")
        canvas.configure(bg="#0c1725")
        text(g.plans[floor].name, 10, 20, size=10)
        if floor == 0:
            band(6.3, 16.7, .02 * math.pi, .98 * math.pi, "#172b40")
            band(17.1, 22.2, .02 * math.pi, .98 * math.pi, "#26364b")
            for region, color in (("rim", "#314d65"), ("corridor", "#263f52")):
                b = g.regions[region]
                band(b.minR, b.maxR, b.minAngle * math.pi, b.maxAngle * math.pi, color)
            barrier = g.orchestraBarrier
            cursor, half = .02 * math.pi, barrier.accessWidth / barrier.radius / 2
            for fraction in barrier.accessAngles:
                theta = fraction * math.pi
                if theta - half > cursor:
                    band(barrier.radius - barrier.width / 2, barrier.radius + barrier.width / 2,
                         cursor, theta - half, "#e49a64")
                cursor = theta + half
            if cursor < .98 * math.pi:
                band(barrier.radius - barrier.width / 2, barrier.radius + barrier.width / 2,
                     cursor, .98 * math.pi, "#e49a64")
            label = G.point(16.9, .5 * math.pi, g)
            text("BARRIER: 6 ACCESS POINTS", *pt(label), "#f5c493", 8)
            for region in ("foyer", "stage-east", "stage-west"):
                b = g.regions[region]
                x, y = pt(Record(x=b.minX, y=b.minY))
                xx, yy = pt(Record(x=b.maxX, y=b.maxY))
                canvas.create_rectangle(x, y, xx, yy, fill="#243d51", outline="#66879b", tags="static")
            text("FOYER", *pt(Record(x=-2, y=38)), size=10)
            # These outdoor stairs are context only. Evacuation has already
            # finished at their first-floor doorway thresholds by user instruction.
            for i in range(12):
                line([Record(x=-7, y=42 + i * .4), Record(x=7, y=42 + i * .4)], "#547388")
            text("OUTDOOR STAIRS: AFTER EXIT", *pt(Record(x=-8, y=47.4)), "#8aabbf", 7)
            for fraction in (.17, .83):
                for i in range(5):
                    r = 28 + i * .3
                    line([G.point(r, fraction * math.pi - .03, g), G.point(r, fraction * math.pi + .03, g)], "#547388")
        else:
            band(15.7, 22.75, .02 * math.pi, .98 * math.pi, "#243c52")
            b = g.regions["balcony-rim"]
            band(b.minR, b.maxR, b.minAngle * math.pi, b.maxAngle * math.pi, "#314f66")
            text("OPEN TO FIRST FLOOR", *pt(Record(x=-8, y=18)), "#7798ae", 9)
        for section in g.sections:
            if section.floor != floor:
                continue
            for row in range(section.rows):
                r = section.firstR + row * section.step
                boundaries = [.02, *g.aisleAngles, .98]
                for left, right in zip(boundaries, boundaries[1:]):
                    lo, hi = left * math.pi + g.aisleHalfWidth / r, right * math.pi - g.aisleHalfWidth / r
                    if lo < hi:
                        line(arc(r, lo, hi), "#516d83", 2)
        for seat in engine.seats:
            if seat.floor == floor:
                x, y = pt(seat)
                canvas.create_rectangle(x - 1.1, y - 1.1, x + 1.1, y + 1.1,
                                        fill="#7a91a4", outline="", tags="static")
        for p in engine.portals:
            if p.floor != floor:
                continue
            if p.type == "access":
                entry = g.entrances[p.toEntrance]
                line([p, entry], "#94d6fa", 3)
            if p.type == "stairs" and p.id.startswith("BACK_"):
                # Diagram the two parallel flights/lanes; actual transit is a
                # lane queue with two flight times, not planar stair integration.
                for lane in (-1, 1):
                    x = p.x + lane * .5
                    line([Record(x=x, y=p.y), Record(x=x, y=p.y + 2)], "#b3a2f0", 2)
                line([Record(x=p.x, y=p.y), Record(x=p.x, y=p.y + 2)], "#f5d292", 2)
        for entry in g.entrances.values():
            if entry.floor == floor:
                x, y = pt(entry)
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, outline="#88bfe7", tags="static")
        canvas._bailey_geometry_key = key
        canvas._led_geometry_key = None
    canvas.delete("dynamic")
    led = engine.led
    led_key = (key, led.revision, led.config.showStrips) if led else (key, None)
    if getattr(canvas, "_led_geometry_key", None) != led_key:
        canvas.delete("led")
        if led is not None and led.config.showStrips:
            for path in led.display_paths():
                if path.floor == floor and len(path.points) > 1:
                    canvas.create_line(*flat(path.points), fill="#36dba4", width=1.5,
                                       arrow="last", arrowshape=(5, 6, 2), tags="led")
        canvas._led_geometry_key = led_key
    for p in engine.portals:
        if p.floor != floor:
            continue
        x, y = pt(p)
        color = "#6fe3ba" if p.type == "exit" else "#b9a5ff" if p.type == "stairs" else "#f4b36e"
        if not p.evacuationAllowed: color = "#8c919b"
        elif not p.enabled: color = "#ef7c85"
        if p.type == "exit":
            tangent = Record(x=-p.normal.y * p.width / 2, y=p.normal.x * p.width / 2)
            line([Record(x=p.x - tangent.x, y=p.y - tangent.y),
                  Record(x=p.x + tangent.x, y=p.y + tangent.y)], color, 4, "dynamic")
        else:
            canvas.create_oval(x - 3.5, y - 3.5, x + 3.5, y + 3.5, fill=color, outline="", tags="dynamic")
        label = p.id + (" EXCLUDED" if not p.evacuationAllowed else "")
        if p.get("lanes"):
            label += " [" + "/".join(str(len(lane.agents)) for lane in p.lanes) + "]"
        text(label, x + 5, y - 5, color, 7, "dynamic")
    colors = {"row": "#edb867", "aisle": "#7bd2ef", "foyer": "#b7a5fd"}
    if led is not None and led.config.showStrips:
        text("LED strips: shortest-route directions", 10, height-31, "#36dba4", 8, "dynamic")
    if engine.crowd is not None:
        for manager in engine.crowd.managers:
            if manager.floor != floor: continue
            x, y = pt(manager)
            if engine.crowd.config.showCoverage:
                radius = engine.crowd.config.communicationRange * scale
                # Outline is the range bound; walls still occlude actual signals.
                canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline="#826f3b",
                                   dash=(3, 4), tags="dynamic")
            r = max(4., manager.radius * scale)
            canvas.create_polygon(x, y-r, x-r, y+r, x+r, y+r, fill="#ffe274", outline="#161616", tags="dynamic")
            text(manager.managerId, x+6, y+7, "#ffe274", 8, "dynamic")
        if selected is not None and selected < len(engine.agents):
            agent = engine.agents[selected]
            if agent.floor == floor and "guidance" in agent.data:
                memory = agent.data.guidance.memory
                if memory:
                    route = " > ".join(memory.portals)
                    text(f"{memory.managerId}: {route}", 10, height-16, "#ffe274", 8, "dynamic")
    for a in engine.agents:
        if a.floor != floor or a.exited:
            continue
        x, y = pt(a)
        r = max(1.8, a.radius * scale)
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=colors.get(a.region, "#6ed7b4"),
                           outline="white" if a.id == selected else "", width=2, tags="dynamic")
    return Record(scale=scale, ox=ox, oy=oy)
