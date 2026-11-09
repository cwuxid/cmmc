"""Optional hidden-window smoke test: python -m unittest -v test_visualize.py."""
import unittest
from unittest.mock import patch

from auditorium import Simulation


class AnimationTests(unittest.TestCase):
    def test_tk_controls_and_completion(self):
        # Graphics is optional: absent Tcl/Tk or a display should skip this smoke
        # test, while the separate headless engine tests can still run normally.
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as error:
            self.skipTest(f"Optional tkinter is unavailable: {error}")
        from visualize import animate

        # Save the real constructor before temporarily substituting a hidden window.
        original_tk = tk.Tk
        sim = Simulation({"participants": 5, "seed": 11, "geometry": {"size": 11}})
        # Tk callback exceptions do not automatically propagate to unittest.
        # Retain them and re-raise after the event loop exits to avoid false passes.
        errors = []
        checked = []

        def children(widget):
            # Buttons are inside nested layout frames, so inspect descendants.
            for child in widget.winfo_children():
                yield child
                yield from children(child)

        def hidden_window():
            try:
                root = original_tk()
            except tk.TclError as error:
                self.skipTest(f"A Tk display is unavailable: {error}")
            root.withdraw()

            def exercise():
                try:
                    widgets = list(children(root))
                    buttons = [w for w in widgets if isinstance(w, ttk.Button)]
                    run = next(w for w in buttons if w.cget("text") == "Run")
                    step = next(w for w in buttons if w.cget("text") == "One step")
                    step.invoke()
                    self.assertEqual(sim.time, 1)
                    run.invoke()
                    self.assertEqual(run.cget("text"), "Pause")
                    run.invoke()
                    self.assertEqual(run.cget("text"), "Run")
                    for _ in range(1000):
                        # Exercise the actual Step button rather than calling the
                        # model directly, checking the UI-to-engine connection.
                        if sim.finished:
                            break
                        step.invoke()
                    self.assertTrue(sim.complete)
                    self.assertTrue(run.instate(["disabled"]))
                    self.assertTrue(step.instate(["disabled"]))
                    checked.append(True)
                except Exception as error:
                    errors.append(error)
                finally:
                    # Close the hidden window even when an assertion fails.
                    root.destroy()

            # Wait for animate() to construct its widgets before invoking controls.
            root.after(20, exercise)
            return root

        with patch.object(tk, "Tk", hidden_window):
            # Patching only window creation leaves the real widgets and callbacks
            # in place and avoids showing a window during automated verification.
            animate(sim)
        if errors:
            raise errors[0]
        self.assertEqual(checked, [True])


if __name__ == "__main__":
    unittest.main()
