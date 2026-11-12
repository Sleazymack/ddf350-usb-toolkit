"""Entry-point routing with fake windows, reader and instance APIs only."""
from pathlib import Path
import sys
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import sync_tray
import wizard
import i18n


class LaunchModeTests(unittest.TestCase):
    def setUp(self):
        self.guard=mock.patch.object(i18n,'load_language',return_value='fr')
        self.guard.start();self.addCleanup(self.guard.stop)
        self.addCleanup(i18n.set_language,'fr')
    def test_normal_launch_opens_full_app_instead_of_background_pc_page(self):
        instance=mock.Mock();instance.acquire.return_value=True
        with mock.patch.object(sync_tray,'SingleInstance',return_value=instance), \
             mock.patch.object(app.tk,'Tk') as root, mock.patch.object(wizard,'Wizard') as ui:
            app.main([])
        ui.assert_called_once_with(root.return_value,auto_reader=True,enable_tray=True)
        ui.return_value.show_pc_mode.assert_not_called()
        root.return_value.withdraw.assert_not_called()
        root.return_value.mainloop.assert_called_once();instance.close.assert_called_once()

    def test_explicit_windows_startup_still_uses_minimized_pc_mode(self):
        instance=mock.Mock();instance.acquire.return_value=True
        with mock.patch.object(sync_tray,'SingleInstance',return_value=instance), \
             mock.patch.object(app.tk,'Tk') as root, mock.patch.object(wizard,'Wizard') as ui:
            app.main(['--pc-mode','--minimized'])
        ui.return_value.show_pc_mode.assert_called_once()
        ui.assert_called_once_with(root.return_value,auto_reader=True,enable_tray=True)
        root.return_value.withdraw.assert_called_once()
        root.return_value.after_idle.assert_called_once_with(ui.return_value.hide_to_tray)

    def test_second_normal_launch_requests_full_radio_workflow_without_new_reader(self):
        instance=mock.Mock();instance.acquire.return_value=False
        with mock.patch.object(sync_tray,'SingleInstance',return_value=instance), \
             mock.patch.object(app.tk,'Tk') as root:
            app.main([])
        instance.show_existing.assert_called_once_with(radio=True)
        root.assert_not_called();instance.close.assert_called_once()


if __name__=='__main__':unittest.main()
