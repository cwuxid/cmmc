"""Read-only Tk canvas rendering ported from viewer.js; no movement rules here."""
import math

from . import geometry as G
from .records import Record


def draw(canvas, engine, floor, selected=None):
    from . import plans, plan_viewer
    if plans.active(engine.g):
        return plan_viewer.draw(canvas, engine, floor, selected)
    # Rendering must not mutate coordinates, policy data, metrics, or model time.
    width, height = canvas.winfo_width(), canvas.winfo_height()
    width = width if width > 1 else int(canvas.cget("width"))
    height = height if height > 1 else int(canvas.cget("height"))
    scale, ox, oy = min(width / 69, height / 52), width / 2, 40
    # Shared transform used by app.py for clicks: metres -> canvas pixels.
    # Positive world y points downward on the map, as in the source canvas viewer.
    g = engine.g

    def pt(p): return ox + p.x * scale, oy + p.y * scale
    def text(message, x, y, color="#9aacc0", size=9, tag="static"):
        canvas.create_text(x, y, text=message, fill=color, anchor="w", font=("Segoe UI", size), tags=tag)
    def arc_points(r, start, end):
        # Approximate circular arcs with polylines. This is a drawing resolution
        # choice only; collision geometry uses analytic formulas elsewhere.
        steps = max(2, math.ceil(abs(end - start) * r * scale / 7))
        return [pt(G.point(r, start + (end - start) * k / steps, g)) for k in range(steps + 1)]
    def flatten(points): return [v for p in points for v in p]
    def ring(r0, r1, start, end, fill):
        # Join an outer arc to a reversed inner arc to fill a curved walkway band.
        points = arc_points(r1, start, end) + arc_points(r0, end, start)
        canvas.create_polygon(*flatten(points), fill=fill, outline="", tags="static")
    def ringline(r, start, end, color, line_width=1):
        canvas.create_line(*flatten(arc_points(r, start, end)), fill=color, width=line_width, tags="static")
    def line(a, b, color, line_width=1):
        canvas.create_line(*pt(a), *pt(b), fill=color, width=line_width, tags="static")

    # Geometry is cached between frames; portal state and people remain dynamic.
    key = (id(engine), width, height, floor)
    if getattr(canvas, "_bailey_geometry_key", None) != key:
        # Rebuild static scenery on engine reset, floor change, or canvas resize.
        canvas.delete("all")
        canvas.configure(bg="#0c1725")
        for x in range(-30, 31, 5):
            canvas.create_line(ox + x * scale, 0, ox + x * scale, height, fill="#203144", tags="static")
        for y in range(0, 47, 5):
            canvas.create_line(0, oy + y * scale, width, oy + y * scale, fill="#203144", tags="static")
        text("FIRST FLOOR - orchestra / loge / exits" if floor == 0 else "SECOND FLOOR - balcony",
             16, 20, "#adc8d8", 10)
        ring(0, 26.9, 0, math.pi, "#142438")
        if floor == 0:
            ring(g.auditoriumR, 27.5, 0, math.pi, "#243849")
            ring(g.auditoriumR, 24.15, 0, math.pi, "#29445c")
            ring(24.15, 27.5, 0, math.pi, "#23384c")
            x, y = pt(Record(x=-12, y=32))
            canvas.create_rectangle(x, y, x + 24 * scale, y + 10.3 * scale,
                                    fill="#22374a", outline="#567287", tags="static")
            ringline(g.auditoriumR, 0, math.pi, "#5a7387", 2)
            ringline(27.5, 0, math.pi, "#688195", 2)
            text("FOYER", ox - 18, oy + 38.6 * scale, "#a9bcd0", 10)
            text("STAGE", ox - 21, oy + 6 * scale, "#728da4", 10)
        else:
            ring(g.balconyR, 24.65, 0, math.pi, "#29445d")
            ringline(g.balconyR, 0, math.pi, "#647f94", 2)
            text("OPEN TO AUDITORIUM", ox - 67, oy + 13 * scale, "#69859d", 9)
        for section in g.sections:
            # Seat-row lines show the physical row tracks enforced by the engine.
            if section.floor != floor:
                continue
            for k in range(section.rows):
                r = section.firstR + k * section.step
                aisles = [v * math.pi for v in [.02, *g.aisleAngles, .98]]
                for i in range(len(aisles) - 1):
                    lo, hi = aisles[i] + g.aisleHalfWidth / r, aisles[i + 1] - g.aisleHalfWidth / r
                    if hi > lo:
                        ringline(r, lo, hi, "#48637b", 2.4)
        aisle_max = g.auditoriumR if floor == 0 else g.balconyR
        for fraction in g.aisleAngles:
            theta = fraction * math.pi
            ring(6.2, aisle_max, theta - .008, theta + .008, "#375b72")
            for edge in (-1, 1):
                r0, r1 = (6.3 if floor == 0 else 15.7), aisle_max
                line(G.point(r0, theta + edge * g.aisleHalfWidth / r0, g),
                     G.point(r1, theta + edge * g.aisleHalfWidth / r1, g), "#6688a0", .7)
        for seat in engine.seats:
            # All inventory seats are drawn, including currently unoccupied seats.
            if seat.floor == floor:
                x, y = pt(seat)
                canvas.create_rectangle(x - 1.25, y - 1.25, x + 1.25, y + 1.25,
                                        fill="#557186", outline="", tags="static")
        canvas._bailey_geometry_key = key
    canvas.delete("dynamic")
    # Portals and pedestrians are refreshed every frame; disabled doors use red.
    for portal in engine.portals:
        if portal.floor != floor:
            continue
        x, y = pt(portal)
        r = 5.2 if portal.type == "exit" else 4.3
        color = ("#e66d76" if not portal.enabled else "#6fe3ba" if portal.type == "exit"
                 else "#b19bfa" if portal.type == "stairs" else "#f8bc75")
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="", tags="dynamic")
        text(portal.id, x + 7, y + 3, "#cee2ef" if portal.enabled else "#ffaeb6", 8, "dynamic")
    colors = {"row": "#f2b76a", "aisle": "#7bd2ef", "foyer": "#b7a5fd", "balcony-rim": "#8ad6bd"}
    # Person colors identify current region, not preference weights or exit choice.
    for agent in engine.agents:
        if agent.floor != floor or agent.exited:
            continue
        x, y = pt(agent)
        r = max(1.9, agent.radius * scale)
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=colors.get(agent.region, "#63dfc4"),
                           outline="white" if agent.id == selected else "", width=2.4, tags="dynamic")
        if agent.id == selected:
            canvas.create_oval(x - 8, y - 8, x + 8, y + 8, outline="white", width=1.5, tags="dynamic")
    # The transform is returned for callers that need matching screen coordinates.
    return Record(scale=scale, ox=ox, oy=oy)
