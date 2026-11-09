"""Real hidden-Tk controls regression; every engine has 300 audience members."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bailey_motion import BaileyEngine,UserModel,default_config
from bailey_motion.loader import default_policy_source


class CrowdGuiTests(unittest.TestCase):
    def test_led_controls_draw_strips_and_students_suppress_lighting(self):
        import tkinter as tk
        from bailey_motion.app import BaileyApp
        root=tk.Tk();root.withdraw()
        world=default_config();world.population=300
        app=BaileyApp(root,BaileyEngine(world,UserModel()),default_policy_source())
        try:
            app.led_enabled.set(True);app.led_strength.set('7.5');app.reset_from_form()
            self.assertIsNotNone(app.engine.led);self.assertIsNone(app.engine.crowd)
            self.assertEqual(app.engine.led.config.strength,7.5)
            self.assertTrue(app.ground.find_withtag('led'))
            self.assertTrue(app.upper.find_withtag('led'))
            self.assertIn('LEDs ON: strength 7.5',app.stats.get())
            app.engine.run_steps(20);app.refresh()
            self.assertGreater(app.engine.led.summary()['recommendedDecisions'],0)
            app.students_enabled.set(True);app.update_student_controls()
            self.assertTrue(app.led_checkbox.instate(['disabled']))
            self.assertTrue(app.led_strength_control.instate(['disabled']))
            app.reset_from_form()
            self.assertIsNone(app.engine.led);self.assertIsNotNone(app.engine.students)
            self.assertFalse(app.ground.find_withtag('led'))
            self.assertTrue(app.led_enabled.get())
            app.students_enabled.set(False);app.reset_from_form()
            self.assertIsNotNone(app.engine.led)
            previous=app.engine;app.led_strength.set('-1');app.reset_from_form()
            self.assertIs(app.engine,previous)
            self.assertIn('reset not applied',app.status.get())
        finally:
            app.close()

    def test_invalid_dt_does_not_silently_change_active_mode_or_timestep(self):
        import tkinter as tk
        from bailey_motion.app import BaileyApp
        root=tk.Tk(); root.withdraw()
        world=default_config(); world.population=300
        app=BaileyApp(root,BaileyEngine(world,UserModel()),default_policy_source())
        try:
            previous=app.engine
            app.dt.set('2'); app.students_enabled.set(True)
            app.reset_from_form()
            self.assertIs(app.engine,previous)
            self.assertIsNone(app.engine.students)
            self.assertEqual(app.engine.config.dt,.1)
            self.assertEqual(app.dt.get(),'2')
            self.assertIn('reset not applied',app.status.get())
            app.refresh(); self.assertIn('active dt=0.1 s',app.stats.get())
            app.playback.set(2.)
            self.assertEqual(app.engine.config.dt,.1)
            app.dt.set('.1'); app.reset_from_form()
            self.assertIsNotNone(app.engine.students)
        finally:
            app.close()

    def test_toggle_resets_mode_and_displays_actual_guidance(self):
        import tkinter as tk
        from bailey_motion.app import BaileyApp
        root=tk.Tk(); root.withdraw()
        world=default_config(); world.population=300
        app=BaileyApp(root,BaileyEngine(world,UserModel()),default_policy_source())
        try:
            self.assertIsNone(app.engine.crowd)
            self.assertIn('Managers OFF',app.stats.get())
            app.crowd_enabled.set(True); app.reset_from_form()
            self.assertEqual(len(app.engine.agents),300)
            self.assertEqual(len(app.engine.crowd.managers),6)
            app.engine.run_steps(50); app.refresh()
            self.assertIn('Managers ON: 6',app.stats.get())
            self.assertGreater(app.engine.crowd.summary()['recommendedDecisions'],0)
            self.assertIn('choices changed by bonus',app.stats.get())
            app.students_enabled.set(True); app.update_student_controls()
            self.assertTrue(app.manager_checkbox.instate(['disabled']))
            app.reset_from_form()
            self.assertIsNone(app.engine.crowd)
            self.assertIsNotNone(app.engine.students)
            self.assertTrue(app.crowd_enabled.get())  # preference retained, suppressed
            self.assertIn('Managers OFF (student mode)',app.stats.get())
            app.engine.run_steps(20); app.refresh()
            self.assertGreater(app.engine.students.summary()['decisions'],0)
            app.students_enabled.set(False); app.reset_from_form()
            self.assertIsNone(app.engine.students)
            self.assertEqual(len(app.engine.crowd.managers),6)
            self.assertFalse(app.manager_checkbox.instate(['disabled']))
            app.crowd_enabled.set(False); app.reset_from_form()
            self.assertIsNone(app.engine.crowd)
            self.assertIn('Managers OFF',app.stats.get())
            self.assertEqual(len(app.engine.agents),300)
        finally:
            app.close()


if __name__=='__main__': unittest.main()
