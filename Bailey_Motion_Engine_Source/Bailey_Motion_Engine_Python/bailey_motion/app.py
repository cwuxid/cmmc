"""Desktop counterpart of app.js: controls, trusted policy editor, world editor, exports."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time
import traceback

from .config import default_config, default_policy_settings, validate_config
from .engine import BaileyEngine
from .loader import compile_policy, default_policy_source
from .records import record
from . import viewer

# Reading order: __init__/_build construct the UI; reset/apply_* create a new
# experiment; animation advances engine ticks; refresh only draws and inspects.
# Behavioral choices and physical movement live in user_model.py and engine.py.

class BaileyApp:
    def __init__(self, root, engine, source):
        # Delay Tk imports until a desktop session is requested. Headless users
        # can import the engine/package without a working graphical installation.
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        # Keep editable world data separate from the engine's active copied config.
        # source is the code that produced the policy; defaults support restoration.
        self.engine, self.world, self.policy = engine, record(engine.config), engine.policy
        self.source, self.source_defaults = source, default_policy_source()
        self.world_defaults = default_config()
        self.playing, self.selected = False, None
        # Wall-clock time controls playback scheduling, not simulated physics.
        # accum stores simulated seconds awaiting fixed-dt integration steps.
        self.previous, self.accum, self.last_draw = time.perf_counter(), 0., 0.
        root.title("Bailey Motion Engine - Python port")
        root.geometry("1480x960")
        root.minsize(1050, 720)
        self.status = tk.StringVar(value="Ready - edit policy or step through ticks")
        # Tk variables bind widget contents to Python values. Editing a form field
        # does not change the active world until its apply/reset action runs.
        self.stats = tk.StringVar()
        self.population, self.seed, self.dt = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.playback = tk.DoubleVar(value=engine.config.get("playback", 10))
        self.collisions, self.regions, self.capacity = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        self.crowd_enabled = tk.BooleanVar(value=engine.config.get("crowdManagers", {}).get("enabled", False))
        self.students_enabled = tk.BooleanVar(value=engine.config.get("studentMode", False))
        self.led_enabled = tk.BooleanVar(value=engine.config.get("ledStrips", {}).get("enabled", False))
        self.led_strength = tk.StringVar(value=str(engine.config.get("ledStrips", {}).get("strength", 12.)))
        self._build()
        # Populate controls only after their widgets exist, then render time zero.
        self.form_from_settings()
        self.portal_toggles()
        self.refresh()
        self._timer = root.after(20, self.animation)
        # Route the window manager's close action through callback cleanup.
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        # Layout and event wiring only: button commands delegate work to methods
        # below rather than embedding routing or collision rules in widgets.
        tk, ttk = self.tk, self.ttk
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Bailey Motion Engine / Python", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.stats).pack(side="right")
        bar = ttk.Frame(self.root, padding=(10, 0))
        # Tick controls advance model time; playback sets model seconds per
        # wall-clock second and remains editable during a running experiment.
        bar.pack(fill="x")
        self.run_button = ttk.Button(bar, text="Run", command=self.toggle)
        self.run_button.pack(side="left", padx=3)
        for label, command in (("One tick", lambda: self.step(1)), ("10 ticks", lambda: self.step(10)),
                               ("Reset / apply controls", self.reset_from_form)):
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=3)
        for label, variable, width in (("Population", self.population, 6), ("Seed", self.seed, 9), ("dt (s)", self.dt, 5)):
            ttk.Label(bar, text=label).pack(side="left", padx=(10, 3))
            ttk.Entry(bar, textvariable=variable, width=width).pack(side="left")
        ttk.Label(bar, text="Playback").pack(side="left", padx=(10, 3))
        ttk.Spinbox(bar, from_=0.1, to=100, increment=.5, textvariable=self.playback, width=5).pack(side="left")
        options = ttk.Frame(self.root, padding=(10, 5))
        # Mechanics and audience options apply at the next form-based reset.
        options.pack(fill="x")
        for label, variable in (("Hard collisions", self.collisions), ("Region constraints", self.regions),
                                ("Door capacity", self.capacity), ("Six crowd managers (apply/reset)", self.crowd_enabled),
                                ("Students: shortest routes (apply/reset)", self.students_enabled)):
            control = ttk.Checkbutton(options, text=label, variable=variable)
            control.pack(side="left", padx=8)
            if variable is self.crowd_enabled:
                self.manager_checkbox = control
            if variable is self.students_enabled:
                control.configure(command=self.update_student_controls)
        ttk.Label(options, textvariable=self.status).pack(side="right")
        lighting = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        lighting.pack(fill="x")
        self.led_checkbox = ttk.Checkbutton(lighting, text="LED route strips (apply/reset)", variable=self.led_enabled)
        self.led_checkbox.pack(side="left", padx=8)
        ttk.Label(lighting, text="LED strength (utility bonus)").pack(side="left", padx=(12, 4))
        self.led_strength_control = ttk.Spinbox(lighting, from_=0, to=100, increment=1,
                                               textvariable=self.led_strength, width=7)
        self.led_strength_control.pack(side="left")
        panes = ttk.Panedwindow(self.root, orient="horizontal")
        # Both canvases read the same engine but filter agents by their floor.
        panes.pack(fill="both", expand=True, padx=10, pady=5)
        maps = ttk.Frame(panes)
        editor = ttk.Frame(panes)
        panes.add(maps, weight=3)
        panes.add(editor, weight=2)
        maps.columnconfigure(0, weight=1)
        maps.columnconfigure(1, weight=1)
        maps.rowconfigure(0, weight=1)
        self.ground = tk.Canvas(maps, width=540, height=610, highlightthickness=0)
        self.upper = tk.Canvas(maps, width=540, height=610, highlightthickness=0)
        self.ground.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self.upper.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        self.ground.bind("<Button-1>", lambda event: self.select_agent(event, self.ground, 0))
        self.upper.bind("<Button-1>", lambda event: self.select_agent(event, self.upper, 1))
        self.portal_frame = ttk.LabelFrame(maps, text="Enabled portals (changes apply immediately)", padding=5)
        # Portal switches differ from world settings: they affect live doors
        # immediately, allowing the policy's local closure discovery to be tested.
        self.portal_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)
        tabs = ttk.Notebook(editor)
        # Keep executable policy source, world geometry/distributions, and policy
        # coefficients separately editable. Text is applied only on request.
        tabs.pack(fill="both", expand=True)
        policy_tab, world_tab, settings_tab, inspect_tab = (ttk.Frame(tabs) for _ in range(4))
        tabs.add(policy_tab, text="Python policy")
        tabs.add(world_tab, text="World JSON")
        tabs.add(settings_tab, text="Policy settings")
        tabs.add(inspect_tab, text="Inspector / errors")
        ttk.Label(policy_tab, text="Trusted Python source. Applying code executes it.", wraplength=380).pack(fill="x", pady=5)
        self.code = self._text(policy_tab)
        # The code editor contains a full Python policy module, not a JSON formula.
        self.code.insert("1.0", self.source)
        buttons = ttk.Frame(policy_tab)
        buttons.pack(fill="x", pady=5)
        for label, command in (("Apply code + reset", self.apply_code), ("Restore source", self.restore_code),
                               ("Save policy", lambda: self.save("user_model.py", self.code.get("1.0", "end-1c")))):
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=2)
        self.world_code = self._text(world_tab)
        # World JSON controls seating, dimensions, sampling laws, and engine limits.
        self.world_code.insert("1.0", json.dumps(self.world, indent=2))
        buttons = ttk.Frame(world_tab)
        buttons.pack(fill="x", pady=5)
        for label, command in (("Apply world + reset", self.apply_world), ("Restore world", self.restore_world),
                               ("Save world", lambda: self.save("world.json", json.dumps(self.world, indent=2)))):
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=2)
        self.inspector = self._text(inspect_tab)
        self.inspector.insert("1.0", "Click a pedestrian on either map to inspect it.")
        self.settings_code = self._text(settings_tab)
        # Policy settings control utility, weight covariance, decision timing,
        # shocks, and steering forces without requiring source-code edits.
        self.settings_code.insert("1.0", json.dumps(getattr(self.policy, "settings", {}), indent=2))
        buttons = ttk.Frame(settings_tab)
        buttons.pack(fill="x", pady=5)
        for label, command in (("Apply settings + reset", self.apply_policy_settings),
                               ("Restore settings", self.restore_policy_settings),
                               ("Save settings", lambda: self.save("policy_settings.json", self.settings_code.get("1.0", "end-1c")))):
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=2)
        exports = ttk.Frame(self.root, padding=(10, 5))
        # Exporting reads the current state and does not advance model time.
        exports.pack(fill="x")
        for label, command in (("Save source-format agent CSV", lambda: self.save("bailey_agents.csv", self.engine.agents_csv())),
                               ("Save CSV + utility weights", lambda: self.save("bailey_agents_weights.csv", self.engine.agents_csv(True))),
                               ("Save full run JSON", self.export_run)):
            ttk.Button(exports, text=label, command=command).pack(side="left", padx=3)

    def _text(self, parent):
        # Reusable editor with independent horizontal/vertical scrolling. Text
        # indices such as '1.0' mean line 1, character 0 in Tk's text coordinate system.
        frame = self.ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = self.tk.Text(frame, wrap="none", font=("Consolas", 10), undo=True)
        vertical = self.ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        horizontal = self.ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return text

    def error(self, error):
        # Stop playback on an error and preserve a traceback for diagnosis.
        self.playing = False
        self.run_button.configure(text="Run")
        self.status.set(f"Error: {error}")
        self.inspector.delete("1.0", "end")
        self.inspector.insert("1.0", traceback.format_exc())

    def form_from_settings(self):
        # World -> controls: used after loading/restoring/resetting an experiment.
        self.crowd_enabled.set(self.world.get("crowdManagers", {}).get("enabled", False))
        self.students_enabled.set(self.world.get("studentMode", False))
        self.led_enabled.set(self.world.get("ledStrips", {}).get("enabled", False))
        self.led_strength.set(str(self.world.get("ledStrips", {}).get("strength", 12.)))
        self.population.set(self.world.population)
        self.seed.set(self.world.seed)
        self.dt.set(self.world.dt)
        self.collisions.set(self.world.limits.hardCollisions)
        self.regions.set(self.world.limits.enforceRegions)
        self.capacity.set(self.world.limits.doorCapacity)
        self.update_student_controls()

    def update_student_controls(self):
        # Keep the user's manager preference for when students are switched off;
        # the engine independently enforces precedence, including headless runs.
        self.manager_checkbox.configure(state="disabled" if self.students_enabled.get() else "normal")
        self.led_checkbox.configure(state="disabled" if self.students_enabled.get() else "normal")
        self.led_strength_control.configure(state="disabled" if self.students_enabled.get() else "normal")

    def settings_from_form(self):
        # Controls -> candidate world: parse and validate a copy before replacing
        # the running experiment. Unrelated geometry/distributions remain intact.
        config = record(self.world)
        config.population, config.seed, config.dt = int(self.population.get()), int(self.seed.get()), float(self.dt.get())
        if self.crowd_enabled.get() or "crowdManagers" in config:
            config.setdefault("crowdManagers", record({}))["enabled"] = bool(self.crowd_enabled.get())
        if self.students_enabled.get() or "studentMode" in config:
            config.studentMode = bool(self.students_enabled.get())
        if self.led_enabled.get() or "ledStrips" in config:
            lighting = config.setdefault("ledStrips", record({}))
            lighting.update(enabled=bool(self.led_enabled.get()), strength=float(self.led_strength.get()))
        config.limits.hardCollisions = self.collisions.get()
        config.limits.enforceRegions = self.regions.get()
        config.limits.doorCapacity = self.capacity.get()
        return validate_config(config)

    def reset(self, world=None, policy=None):
        # Build a replacement before swapping the displayed engine. A reset
        # resamples the population from the configured seed and returns to time zero.
        candidate_world = self.world if world is None else world
        candidate_policy = self.policy if policy is None else policy
        engine = BaileyEngine(candidate_world, candidate_policy)
        self.world, self.policy, self.engine = record(candidate_world), candidate_policy, engine
        self.selected, self.playing, self.accum = None, False, 0.
        # Discard any playback backlog and selection from the previous population.
        self.previous = time.perf_counter()
        self.run_button.configure(text="Run")
        self.status.set("Ready - edit policy or step through ticks")
        self.form_from_settings()
        self.portal_toggles()
        self.settings_code.delete("1.0", "end")
        self.settings_code.insert("1.0", json.dumps(getattr(self.policy, "settings", {}), indent=2))
        self.refresh()

    def reset_from_form(self):
        # The Reset/apply-controls button is the boundary for form validation errors.
        try:
            self.reset(self.settings_from_form())
        except Exception as error:
            self.error(error)
            self.status.set(f"Error: reset not applied; active dt={self.engine.config.dt:g} s. {error}")

    def apply_code(self):
        # Compile trusted Python, keep the currently applied policy settings, and
        # reset. 'end-1c' omits Tk's automatically appended trailing newline.
        try:
            source = self.code.get("1.0", "end-1c")
            policy = compile_policy(source, getattr(self.policy, "settings", None))
            self.reset(policy=policy)
            self.source = source
        except Exception as error:
            self.error(error)

    def restore_code(self):
        # Restore the editor buffer only; Apply code is required to execute it.
        self.code.delete("1.0", "end")
        self.code.insert("1.0", self.source_defaults)

    def apply_policy_settings(self):
        # Rebuild the current compiled source with new coefficients. This does
        # not silently execute any unapplied edits in the Python source tab.
        try:
            settings = json.loads(self.settings_code.get("1.0", "end-1c"))
            if not isinstance(settings, dict):
                raise ValueError("Policy settings must be a JSON object.")
            self.reset(policy=compile_policy(self.source, settings))
        except Exception as error:
            self.error(error)

    def restore_policy_settings(self):
        # Restore coefficient defaults while retaining the applied policy source.
        try:
            self.reset(policy=compile_policy(self.source, default_policy_settings()))
        except Exception as error:
            self.error(error)

    def apply_world(self):
        # Parse full world JSON, validate it, then rebuild geometry and population.
        try:
            self.reset(validate_config(record(json.loads(self.world_code.get("1.0", "end-1c")))))
        except Exception as error:
            self.error(error)

    def restore_world(self):
        # Restore the bundled world and update its editor; retain the current policy.
        try:
            self.reset(record(self.world_defaults))
            self.world_code.delete("1.0", "end")
            self.world_code.insert("1.0", json.dumps(self.world, indent=2))
        except Exception as error:
            self.error(error)

    def portal_toggles(self):
        # New engines have new portal objects, so rebuild checkboxes after reset.
        for child in self.portal_frame.winfo_children():
            child.destroy()
        self.portal_variables = {}
        for i, portal in enumerate(self.engine.portals):
            variable = self.tk.BooleanVar(value=portal.enabled)
            self.portal_variables[portal.id] = variable
            def change(p=portal, v=variable):
                # Bind this iteration's portal/variable as defaults. Without this,
                # all callbacks would reference the final loop iteration in Python.
                p.enabled = v.get()
                self.refresh()
            excluded = not portal.get("evacuationAllowed", True)
            button = self.ttk.Checkbutton(self.portal_frame, text=portal.id + (" [excluded]" if excluded else ""),
                                           variable=variable, command=change)
            button.grid(row=i // 6, column=i % 6, sticky="w", padx=5)
            if excluded:
                button.state(["disabled"])

    def toggle(self):
        # Pausing preserves engine state. A finished engine needs Reset to run again.
        if not self.engine.finished:
            self.playing = not self.playing
            self.run_button.configure(text="Pause" if self.playing else "Run")
            self.status.set("Running Python policy" if self.playing else "Paused")

    def step(self, count=1):
        # Manual stepping stops autoplay first, then advances a fixed tick count.
        try:
            self.playing = False
            self.run_button.configure(text="Run")
            self.engine.run_steps(count)
            self.refresh()
        except Exception as error:
            self.error(error)

    def refresh(self):
        # Drawing and inspection are read-only: refresh must never call step().
        viewer.draw(self.ground, self.engine, 0, self.selected)
        viewer.draw(self.upper, self.engine, 1, self.selected)
        e = self.engine
        rows = sum(a.region == "row" for a in e.agents)
        # Rejection counters count failed collision/region queries, not unique people.
        self.stats.set(f"{e.t:.1f} s | active dt={e.config.dt:g} s | exited {e.done}/{len(e.agents)} | in rows {rows} | "
                       f"collision / region rejections {e.metrics.collisionRejections} / {e.metrics.regionRejections}")
        if e.students is not None:
            self.stats.set(self.stats.get() + " | Students: shortest routes")
        if e.plan_layout:
            counts = e.summary()["planOccupancy"]
            self.stats.set(self.stats.get() + f"\nMain {counts.get('main', 0)} | Balcony {counts.get('balcony', 0)} | In transfer {counts.get('transit', 0)}")
        if e.crowd is not None and e.crowd.managers:
            guidance = e.crowd.summary()
            self.stats.set(self.stats.get() + f"\nManagers ON: 6 | reached {guidance['peopleReached']}/{len(e.agents)}"
                           f" | guided decisions {guidance['recommendedDecisions']}"
                           f" | choices changed by bonus {guidance['changedChoiceDecisions']}")
        else:
            self.stats.set(self.stats.get() + ("\nManagers OFF (student mode)" if e.students else "\nManagers OFF"))
        if e.led is not None:
            lighting = e.led.summary()
            self.stats.set(self.stats.get() + f"\nLEDs ON: strength {lighting['strength']:g}"
                           f" | guided decisions {lighting['recommendedDecisions']}"
                           f" | choices changed {lighting['changedChoiceDecisions']}")
        elif e.students and e.config.get("ledStrips", {}).get("enabled", False):
            self.stats.set(self.stats.get() + " | LEDs OFF (student mode)")
        if e.done == len(e.agents):
            times = sorted(a.exitAt for a in e.agents)
            time95 = times[math.ceil(.95 * len(e.agents)) - 1]
            self.stats.set(self.stats.get() + f"\nClearance {max(times):.3f} s | 95% exited {time95:.3f} s")
        if e.finished:
            # Full clearance and maximum-time termination are different outcomes.
            self.playing = False
            self.run_button.configure(text="Run")
            self.status.set("All agents exited" if e.done == len(e.agents) else "Max simulated time reached")
        if self.selected is not None and self.selected < len(e.agents):
            # Show the full current agent record, including custom policy data,
            # sampled utility weights, selected portal, and cached shocks.
            self.inspector.delete("1.0", "end")
            self.inspector.insert("1.0", json.dumps(e.agents[self.selected], indent=2))

    def select_agent(self, event, canvas, floor):
        # Invert viewer.py's metres-to-pixels transform to locate a clicked person.
        width, height = canvas.winfo_width(), canvas.winfo_height()
        scale = min(width / 69, height / 52)
        wx, wy = (event.x - width / 2) / scale, (event.y - 40) / scale
        nearest, score = None, math.inf
        for a in self.engine.agents:
            if a.floor != floor or a.exited:
                continue
            d = (a.x - wx) ** 2 + (a.y - wy) ** 2
            if d < score:
                nearest, score = a, d
        self.selected = nearest.id if nearest is not None and score < 1.3 ** 2 else None
        # The 1.3 m click tolerance is an inspection convenience, not a body radius.
        self.refresh()

    def save(self, filename, contents):
        # User-chosen saves remain inside this port and use exclusive creation,
        # protecting source files and previous experiment outputs from overwrite.
        from tkinter import filedialog
        from .cli import PORT_ROOT
        try:
            path = filedialog.asksaveasfilename(parent=self.root, initialdir=PORT_ROOT / "results",
                                              initialfile=filename, defaultextension=Path(filename).suffix)
            if not path:
                return
            destination = Path(path).resolve()
            if not destination.is_relative_to(PORT_ROOT):
                raise ValueError("Save files inside the Python port directory.")
            with destination.open("x", encoding="utf-8", newline="") as output:
                output.write(contents)
            self.status.set(f"Saved {destination.name}")
        except Exception as error:
            self.error(error)

    def export_run(self):
        # Include source as well as parameters/state so the experiment's policy
        # can be reviewed later. Exports do not include every historical position.
        payload = self.engine.export()
        payload["policySource"] = self.source
        self.save("bailey_run.json", json.dumps(payload, indent=2, allow_nan=False))

    def animation(self):
        # Tk calls this periodically. Fixed-dt physics is independent of rendering
        # frequency: elapsed wall time contributes to a simulated-time accumulator.
        try:
            now = time.perf_counter()
            wall = min(.12, now - self.previous)
            # Cap a delayed frame so UI stalls do not create an enormous backlog.
            self.previous = now
            if self.playing:
                playback = float(self.playback.get())
                if not math.isfinite(playback) or playback <= 0:
                    raise ValueError("Playback must be finite and positive.")
                self.accum += wall * playback
                count = 0
                while self.accum >= self.engine.config.dt and count < 150 and self.playing:
                    # Limit work per callback to leave time for input and redraws.
                    self.engine.step()
                    self.accum -= self.engine.config.dt
                    count += 1
                    if self.engine.finished:
                        self.playing = False
            if now - self.last_draw > .045:
                # Redraw less frequently than the scheduler; many ticks may occur
                # between frames without changing the definition of a model tick.
                self.refresh()
                self.last_draw = now
        except Exception as error:
            self.error(error)
        self._timer = self.root.after(20, self.animation)
        # Scheduling instead of sleeping keeps Tk's event loop responsive.

    def close(self):
        # Cancel the pending callback before destroying its widgets. The CLI can
        # then export the current, possibly incomplete experiment after return.
        self.playing = False
        self.root.after_cancel(self._timer)
        self.root.destroy()


def run_gui(engine, source):
    # Entry point shared by the CLI and scripts. A regular Tcl/Tk installation
    # and accessible desktop are required; the core engine has neither dependency.
    try:
        import tkinter as tk
        root = tk.Tk()
    except (ImportError, RuntimeError) as error:
        raise RuntimeError(f"The desktop app requires working Python Tcl/Tk: {error}") from error
    except Exception as error:
        raise RuntimeError(f"Cannot initialize Tk: {error}. Use headless mode instead.") from error
    app = BaileyApp(root, engine, source)
    root.mainloop()
    # Resets may have replaced the original engine/source, so return the final pair.
    return app.engine, app.source
