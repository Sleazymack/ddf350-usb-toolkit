"""Tray event routing with fake APIs only; no actual notification icon."""
import ctypes as C
from pathlib import Path
import queue
import sys
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sync_tray as tray


class TrayTests(unittest.TestCase):
    def setUp(self):
        self.events=queue.Queue();self.icon=tray.TrayIcon(self.events)
        self.icon.user=mock.Mock();self.icon.shell=mock.Mock()
        self.icon.taskbar_message=50000;self.icon.show_message=50001
        self.icon.hwnd=123;self.icon._icons=[10,11]
    def test_icon_buffers_and_connected_status_differ(self):
        a,b=tray.icon_pixels(False),tray.icon_pixels(True)
        self.assertEqual(len(a[0]),128);self.assertEqual(len(a[1]),4096)
        self.assertNotEqual(a[1],b[1])
    def test_open_and_quit_menu_actions_are_queued_to_tk(self):
        self.icon._window_proc(123,tray.CALLBACK,1,tray.WM_LBUTTONDBLCLK)
        self.assertEqual(self.events.get_nowait(),('open',None))
        self.icon.user.TrackPopupMenu.return_value=1002
        self.icon._window_proc(123,tray.CALLBACK,1,tray.WM_RBUTTONUP)
        self.assertEqual(self.events.get_nowait(),('quit',None))
        self.icon.user.DestroyMenu.assert_called_once()
    def test_explorer_restart_recreates_icon_and_reports_availability(self):
        with mock.patch.object(self.icon,'_notify',return_value=True) as notify:
            self.icon.available=True
            self.icon._window_proc(123,50000,0,0)
        notify.assert_called_once_with(0)
        self.assertEqual(self.events.get_nowait(),('tray_ready',True))

    def test_normal_launch_can_request_radio_workflow_in_existing_process(self):
        self.icon._window_proc(123,self.icon.show_message,1,0)
        self.assertEqual(self.events.get_nowait(),('radio',None))
    def test_connected_updates_only_when_state_changes(self):
        self.icon.set_connected(True);self.icon.set_connected(True)
        self.icon.user.PostMessageW.assert_called_once_with(123,tray.UPDATE,0,0)
    def test_close_removes_notification_before_destroying_window(self):
        with mock.patch.object(self.icon,'_notify') as notify:
            self.icon._window_proc(123,tray.WM_CLOSE,0,0)
        notify.assert_called_once_with(2);self.icon.user.DestroyWindow.assert_called_once_with(123)

    @unittest.skipUnless(sys.platform=='win32','Windows mutex ABI')
    def test_second_instance_reports_existing_and_releases_its_handle(self):
        api=mock.Mock();api.CreateMutexW.return_value=456
        with mock.patch.object(tray.C,'WinDLL',return_value=api),mock.patch.object(tray.C,'get_last_error',return_value=183):
            instance=tray.SingleInstance()
            self.assertFalse(instance.acquire());self.assertTrue(instance.already_running)
            instance.show_existing();instance.close()
        api.PostMessageW.assert_called_once();api.CloseHandle.assert_called_once_with(456)


if __name__=='__main__':unittest.main()
