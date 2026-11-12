"""Compact window geometry and automatic read-only reader lifecycle.

Own transparent test windows only; no USB access, game control or flashing.
"""
import importlib.util
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
HAVE_TK=importlib.util.find_spec('tkinter') is not None
if HAVE_TK:
    import tkinter as tk
    import wizard
    from pc import ddf350_hid as hid


@unittest.skipUnless(HAVE_TK,'Tk unavailable')
class CompactWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.guard=mock.patch.object(hid.Reader,'start',side_effect=AssertionError('Unexpected physical reader'))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.root=tk.Tk();self.root.attributes('-alpha',0)
        if sys.platform=='win32':self.root.wm_attributes('-toolwindow',True)
        self.ui=wizard.Wizard(self.root);self.root.update()
    def tearDown(self):
        self.ui.busy=False
        if not self.ui.closed:self.ui.close()
    def assert_visible(self,widget):
        x=widget.winfo_rootx()-self.root.winfo_rootx()
        y=widget.winfo_rooty()-self.root.winfo_rooty()
        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+widget.winfo_width(),self.root.winfo_width())
        self.assertLessEqual(y+widget.winfo_height(),self.root.winfo_height())
    def test_fixed_four_to_three_window_and_footer_in_every_step(self):
        self.assertEqual(tuple(map(int,self.root.resizable())),(0,0))
        self.assertEqual(self.root.winfo_width()*3,self.root.winfo_height()*4)
        self.assertLessEqual(self.root.winfo_width(),800)
        for step in range(1,8):
            self.ui.step=step;self.ui.render();self.root.update()
            with self.subTest(step=step):
                self.assert_visible(self.ui.forward);self.assert_visible(self.ui.back)
                self.assert_visible(self.ui.game_label)
                if step==6:self.assert_visible(self.ui.log_view)
    def test_compact_editor_has_visible_preview_controls_and_footer(self):
        self.ui.choose_custom();self.root.update()
        editor=self.ui.inline_editor
        self.assertTrue(editor.compact)
        self.assert_visible(editor.canvas)
        self.assertGreater(editor.canvas.winfo_height(),200)
        for widget in (editor.widget_combo,editor.channel_combo,editor.kind_combo,editor.color_button,self.ui.forward):
            self.assert_visible(widget)
    def test_auto_reader_starts_once_and_stops_on_close(self):
        self.ui.close()
        self.root=tk.Tk();self.root.withdraw()
        reader=mock.Mock();reader.is_alive.return_value=True
        with mock.patch.object(hid,'Reader',return_value=reader):
            self.ui=wizard.Wizard(self.root,auto_reader=True)
            self.ui.start_game_reader()
        reader.start.assert_called_once()
        self.root.update_idletasks()
        self.ui.close();reader.request_stop.assert_called_once()
    def test_data_and_disconnect_are_reflected_without_a_viewer_window(self):
        self.ui.game_events.put(('data',hid.Channels(123,987),time.monotonic()))
        self.ui.poll_game_reader()
        self.assertIn('123',self.ui.game_status.get());self.assertIn('987',self.ui.game_status.get())
        self.assertIsNone(self.ui.viewer)
        self.ui.game_events.put(('disconnected','USB unplugged',time.monotonic()))
        self.ui.poll_game_reader()
        self.assertIsNone(self.ui.game_values)
        self.assertEqual(wizard.tr('USB · en attente de la radio · reconnexion automatique'),self.ui.game_status.get())

    def test_manual_poll_does_not_leave_duplicate_callbacks(self):
        old=self.ui.poll_id
        self.ui.poll()
        self.assertNotIn(old,self.root.tk.call('after','info'))
        self.assertIn(self.ui.poll_id,self.root.tk.call('after','info'))

    def test_pc_page_is_reachable_directly_and_shows_inputs_in_fixed_window(self):
        with mock.patch.object(self.ui,'start_game_reader') as reader, mock.patch('pc_startup.is_enabled',return_value=False):
            self.ui.pc_button.invoke()
            reader.assert_called_once()
        self.root.update()
        self.assertTrue(self.ui.pc_mode)
        self.assertFalse(self.ui.version_confirmed)
        self.assertEqual(len(self.ui.pc_panels),2)
        for _,number,canvas in self.ui.pc_panels:
            self.assert_visible(number);self.assert_visible(canvas)
        self.assert_visible(self.ui.startup_check);self.assert_visible(self.ui.forward)
        self.ui.game_events.put(('data',hid.Channels(321,765),time.monotonic()))
        self.ui.poll_game_reader()
        self.assertEqual(self.ui.pc_panels[0][1].cget('text'),'321')
        self.assertEqual(self.ui.pc_panels[1][1].cget('text'),'765')
        self.ui.previous();self.assertFalse(self.ui.pc_mode)
        self.assertEqual(self.ui.step,1)

    def test_startup_setting_is_only_written_on_explicit_checkbox_action(self):
        with mock.patch('pc_startup.is_enabled',return_value=False),mock.patch('pc_startup.enable') as enable,mock.patch('pc_startup.disable') as disable:
            self.ui.show_pc_mode(start_reader=False)
            enable.assert_not_called();disable.assert_not_called()
            self.ui.startup_check.invoke();enable.assert_called_once()
            self.ui.startup_check.invoke();disable.assert_called_once()

    def test_window_close_hides_to_tray_but_menu_quit_stops_reader_and_closes(self):
        icon=mock.Mock();icon.available=True
        self.ui.tray=icon
        self.ui.window_close()
        self.assertFalse(self.ui.closed);self.assertTrue(self.ui.hide_requested)
        self.ui.tray_events.put(('open',None));self.ui.poll_tray()
        self.assertFalse(self.ui.hide_requested)
        self.ui.tray_events.put(('quit',None));self.ui.poll_tray()
        self.assertTrue(self.ui.closed);icon.close.assert_called_once()

    def test_radio_editor_and_pc_reader_are_reachable_in_the_same_window(self):
        self.ui.choose_custom();editor=self.ui.inline_editor
        layout=editor.get_layout()
        with mock.patch.object(self.ui,'start_game_reader'),mock.patch('pc_startup.is_enabled',return_value=False):
            self.ui.play_button.invoke()
        self.assertTrue(self.ui.pc_mode)
        self.assertEqual(self.ui.custom_layout,layout)
        self.root.update();self.assert_visible(self.ui.radio_button);self.assert_visible(self.ui.play_button)
        self.ui.radio_button.invoke();self.root.update()
        self.assertFalse(self.ui.pc_mode)
        self.assertEqual(self.ui.step,3)
        self.assertEqual(self.ui.inline_editor.get_layout(),layout)
        self.assert_visible(self.ui.forward)

    def test_navigation_cannot_interrupt_transfer(self):
        self.ui.step=6;self.ui.render();self.ui.busy=True
        self.ui.play_button.invoke();self.ui.radio_button.invoke()
        self.assertFalse(self.ui.pc_mode);self.assertEqual(self.ui.step,6)

    def test_second_normal_launch_reopens_radio_workflow_from_background(self):
        with mock.patch('pc_startup.is_enabled',return_value=False):self.ui.show_pc_mode(start_reader=False)
        self.ui.hide_to_tray()
        self.ui.tray_events.put(('radio',None));self.ui.poll_tray()
        self.assertFalse(self.ui.pc_mode);self.assertFalse(self.ui.hide_requested)

    def test_completed_installation_can_start_another_dashboard(self):
        self.ui.step=7;self.ui.identity={'old':'identity'};self.ui.target=b'old'
        self.ui.show_radio_mode()
        self.assertEqual(self.ui.step,1);self.assertFalse(self.ui.version_confirmed)
        self.assertIsNone(self.ui.identity);self.assertIsNone(self.ui.target)


if __name__=='__main__':unittest.main()
