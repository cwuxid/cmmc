"""Optional live animation using tkinter; no pip packages needed."""
from __future__ import annotations

import json

from auditorium import Simulation

# Colors identify chosen door IDs, not personality profiles or utility magnitudes.
COLORS = ("#69d5ba", "#efb462", "#a89bea", "#ed8fa7", "#80c5e9", "#dce779")


def animate(sim: Simulation, steps_per_frame: int = 3) -> None:
    # The passed Simulation owns all state and rules. This function only controls
    # when step() runs and how the resulting state is displayed.
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError("Animation requires tkinter. Install Python with Tcl/Tk support, or omit --animate.") from error
    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError(f"Cannot open a graphical display: {error}. Omit --animate for a headless run.") from error
    root.title("Auditorium movement model — Python")
    root.configure(bg="#14212c")
    root.minsize(740, 650)
    # Start paused so the user can inspect the initial population before movement.
    running = False
    selected = None
    pixels = 720
    b = sim.building
    # Display pixels are separate from abstract model cells; resizing this drawing
    # scale would not change walking speed, door capacity, or utility features.
    scale = pixels / b.size

    title = tk.Label(root, text="Auditorium movement laboratory", font=("Segoe UI", 18, "bold"),
                     bg="#14212c", fg="#edf4fa")
    title.pack(padx=16, pady=(14, 6))
    status = tk.StringVar()
    tk.Label(root, textvariable=status, bg="#14212c", fg="#8ddac7", font=("Segoe UI", 10)).pack(pady=5)
    controls = ttk.Frame(root)
    controls.pack(padx=16, pady=7)
    canvas = tk.Canvas(root, width=pixels, height=pixels, bg="#0b131b", highlightthickness=0)
    canvas.pack(padx=16, pady=10)
    speed = tk.IntVar(value=steps_per_frame)
    inspector = tk.StringVar(value="Click a participant to inspect its weights.")
    tk.Label(root, textvariable=inspector, bg="#14212c", fg="#c3d3df", wraplength=710,
             font=("Consolas", 9)).pack(padx=16, pady=(0, 12))

    def color(target: int) -> str:
        # Gray means no target has been selected yet. Cycle colors for custom doors.
        return "#91a5b6" if target < 0 else COLORS[target % len(COLORS)]

    # Static geometry is drawn once; moving agents are tagged for replacement.
    for cell, walkable in enumerate(b.walkable):
        if not walkable:
            continue
        x, y = b.position(cell)
        canvas.create_rectangle(x * scale, y * scale, (x + 1) * scale, (y + 1) * scale,
                                fill=color(b.exit_at[cell]) if b.exit_at[cell] >= 0 else "#223340",
                                outline="#16232d", width=0.5)

    def draw() -> None:
        # Replace only the moving layer, leaving static floor/door items untouched.
        canvas.delete("agents")
        radius = scale * 0.32
        for a in sim.agents:
            if a.exited:
                # Exited people remain in the data model but disappear from the room.
                continue
            x, y = b.position(a.cell)
            cx, cy = (x + 0.5) * scale, (y + 0.5) * scale
            canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                               fill=color(a.target), outline="white" if a.id == selected else "",
                               width=2, tags="agents")
        # Status distinguishes completed clearance from an incomplete stopped run.
        summary = sim.summary()
        state = "Complete" if sim.complete else "Step limit" if sim.finished else "Running" if running else "Paused"
        status.set(f"{state}  |  step {sim.time}  |  exited {sim.exited_count}/{len(sim.agents)}"
                   f"  |  conflicts {sim.conflicts}\n" + "   ".join(f"{k}: {v}" for k, v in summary["exitCounts"].items()))
        toggle.configure(text="Pause" if running else "Run", state="disabled" if sim.finished else "normal")
        step_button.configure(state="disabled" if sim.finished else "normal")
        if selected is not None:
            # Inspection reads the agent's stored weights; it never resamples them.
            a = sim.agents[selected]
            weights = ", ".join(f"{key}={value:.3f}" for key, value in a.weights.items())
            target = b.exits[a.target]["name"] if a.target >= 0 else "undecided"
            inspector.set(f"Agent {a.id} | target: {target} | waits: {a.wait_steps} | switches: {a.switches}\n{weights}")

    def toggle_run() -> None:
        nonlocal running
        # A completed or step-limited model cannot be restarted by this button.
        running = not running and not sim.finished
        draw()

    def one_step() -> None:
        # Single stepping pauses playback and advances precisely one model tick.
        nonlocal running
        running = False
        sim.step()
        draw()

    def inspect(event) -> None:
        nonlocal selected
        # Convert a canvas click back to grid coordinates, then consult occupancy.
        x, y = int(event.x / scale), int(event.y / scale)
        if 0 <= x < b.size and 0 <= y < b.size:
            agent_id = sim.occupancy[b.index(x, y)]
            selected = agent_id if agent_id >= 0 else None
        if selected is None:
            inspector.set("Click a participant to inspect its weights.")
        draw()

    toggle = ttk.Button(controls, text="Run", command=toggle_run)
    toggle.pack(side="left", padx=5)
    step_button = ttk.Button(controls, text="One step", command=one_step)
    step_button.pack(side="left", padx=5)
    ttk.Label(controls, text="Steps / frame:").pack(side="left", padx=(15, 5))
    ttk.Spinbox(controls, from_=1, to=100, textvariable=speed, width=5).pack(side="left")
    ttk.Button(controls, text="Print summary", command=lambda: print(json.dumps(sim.summary(), indent=2))).pack(side="left", padx=12)
    canvas.bind("<Button-1>", inspect)

    def frame() -> None:
        nonlocal running
        if running:
            # Playback speed controls steps per redraw, not the physics of a step.
            try:
                count = max(1, min(100, speed.get()))
            except tk.TclError:
                # A partially edited spinbox can temporarily contain invalid text.
                count = 1
            for _ in range(count):
                if not sim.step():
                    running = False
                    break
            if sim.finished:
                running = False
            draw()
        # Schedule the next callback without a blocking sleep, so controls remain
        # responsive. A paused window still processes UI events and future callbacks.
        root.after(40, frame)

    draw()
    root.after(40, frame)
    # Returning from the UI leaves the same Simulation available for CLI export.
    root.mainloop()
