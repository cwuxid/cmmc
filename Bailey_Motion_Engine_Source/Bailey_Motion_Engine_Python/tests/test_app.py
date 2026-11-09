"""Optional real-Tk smoke check. Run outside a restricted desktop sandbox if needed."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bailey_motion import default_config, BaileyEngine, UserModel
from bailey_motion.loader import default_policy_source


class AppTests(unittest.TestCase):
    def test_desktop_controls_editors_and_reset(self):
        # This uses real widgets/callbacks, but withdraws the window so verification
        # does not display an interactive app. Skip if Tcl/Tk cannot initialize.
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as error:
            self.skipTest(f"Tk cannot initialize: {error}")
        root.withdraw()
        from bailey_motion.app import BaileyApp
        config = default_config()
        config.population = 5
        app = BaileyApp(root, BaileyEngine(config, UserModel()), default_policy_source())
        try:
            self.assertEqual(app.engine.g.layoutVersion, 2)
            self.assertEqual(len(app.portal_variables), 34)
            elevator = next(w for w in app.portal_frame.winfo_children() if w.cget("text").startswith("ADA_W"))
            self.assertTrue(elevator.instate(["disabled"]))
            self.assertFalse(app.engine.portal_map["ADA_W"].enabled)
            # Single stepping and Run/Pause must update the same underlying engine.
            app.step(1)
            self.assertEqual(app.engine.tick, 1)
            app.toggle()
            self.assertTrue(app.playing)
            app.toggle()
            self.assertFalse(app.playing)
            app.population.set("7")
            # Applying form controls creates a new seeded population at time zero.
            app.reset_from_form()
            self.assertEqual(len(app.engine.agents), 7)
            app.apply_code()
            self.assertEqual(app.engine.tick, 0)
            app.settings_code.delete("1.0", "end")
            # Settings-only edits should rebuild the current source with overrides.
            app.settings_code.insert("1.0", '{"weightSigma": 0.8}')
            app.apply_policy_settings()
            self.assertEqual(app.policy.settings.weightSigma, .8)
            old = app.engine
            # Invalid world JSON should report an error without replacing the engine.
            app.world_code.delete("1.0", "end")
            app.world_code.insert("1.0", "{")
            app.apply_world()
            self.assertIs(app.engine, old)
            self.assertTrue(app.status.get().startswith("Error:"))
            app.restore_world()
            self.assertEqual(len(app.engine.agents), 300)
        finally:
            # Cancel scheduled callbacks and destroy widgets even after an assertion.
            app.close()


if __name__ == "__main__":
    unittest.main()
