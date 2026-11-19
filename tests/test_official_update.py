"""Stock update navigation and exact bytes, with all physical access disabled."""
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import i18n
import installer
import patch_firmware as patcher
import wizard
from test_installer import FakeDevice, raw_fixture


class OfficialUpdateTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.ui = wizard.Wizard(self.root)
        self.original = Path(self.ui.source.get()).read_bytes()
        for target in ('installer.discover', 'installer.launch_elevated', 'pc.ddf350_hid.Reader.start'):
            guard = mock.patch(target, side_effect=AssertionError('Unexpected hardware access'))
            guard.start()
            self.addCleanup(guard.stop)

    def tearDown(self):
        self.ui.busy = False
        self.ui.close()

    def test_home_button_prepares_exact_stock_ignoring_custom_options(self):
        self.ui.dashboard.set('purple_drift')
        self.ui.fast.set(True)
        self.ui.startup_media = object()
        self.ui.target = b'previous custom target'
        with mock.patch.object(patcher, 'build_patch', side_effect=AssertionError('Must not patch')):
            self.ui.update_button.invoke()
            self.assertTrue(self.ui.official_update)
            self.assertEqual(self.ui.step, 1)
            self.ui.next()
        self.assertEqual(self.ui.step, 5)
        self.assertEqual(self.ui.target, self.original)
        self.assertEqual(self.ui.step_label.cget('text'), i18n.tr('ÉTAPE 2 / 4'))
        self.ui.next()
        self.assertEqual(self.ui.step, 5)
        self.ui.identity = {'letter': 'G'}
        self.ui.next()
        self.assertEqual(self.ui.step, 6)
        with mock.patch.object(self.ui, 'install') as install:
            install.assert_not_called()
            self.ui.next()
            install.assert_called_once()

    def test_official_completion_returns_home_without_starting_reader(self):
        self.ui.show_official_update()
        self.ui.game_enabled = True
        self.ui.worker_handle = 123
        self.ui.step = 6
        self.ui.render()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(installer, 'runs_root', return_value=Path(folder)):
            self.ui.job_directory = Path(folder)
            installer.append_log(self.ui.job_directory, 'done', 'Done')
            with mock.patch.object(installer, 'worker_exit_code', return_value=0), \
                 mock.patch.object(installer, 'close_process'):
                self.ui.poll()
        self.assertEqual(self.ui.step, 7)
        self.assertEqual(self.ui.forward.cget('text'), i18n.tr('Terminer'))
        self.ui.next()
        self.assertFalse(self.ui.official_update)
        self.assertEqual(self.ui.step, 1)
        self.ui.confirm_version()
        self.assertEqual(self.ui.step, 2)

    def test_back_and_mode_switch_clear_stale_detection_and_target(self):
        self.ui.show_official_update()
        self.ui.next()
        self.ui.identity = {'letter': 'G'}
        self.ui.previous()
        self.assertEqual(self.ui.step, 1)
        self.assertTrue(self.ui.official_update)
        self.assertIsNone(self.ui.identity)
        self.assertIsNone(self.ui.target)
        self.ui.previous()
        self.assertFalse(self.ui.official_update)
        self.assertFalse(self.ui.version_confirmed)
        self.ui.show_official_update()
        self.ui.next()
        self.ui.show_pc_mode(start_reader=False)
        self.ui.show_radio_mode()
        self.assertFalse(self.ui.official_update)
        self.assertIsNone(self.ui.target)

    def test_bad_stock_file_is_rejected_before_connecting(self):
        self.ui.show_official_update()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'changed.bin'
            source.write_bytes(self.original[:-1])
            self.ui.source.set(str(source))
            with mock.patch.object(wizard.messagebox, 'showerror') as error:
                self.ui.next()
                error.assert_called_once()
        self.assertEqual(self.ui.step, 1)
        self.assertIsNone(self.ui.target)

    def test_missing_bundle_keeps_file_picker_before_stock_update(self):
        self.ui.source.set('')
        self.ui.show_official_update()
        self.assertTrue(hasattr(self.ui, 'firmware_button'))
        self.ui.next()
        self.assertEqual(self.ui.step, 1)
        self.ui.source.set(app.bundled_firmware_path())
        self.ui.next()
        self.assertEqual(self.ui.target, self.original)

    def test_custom_radio_returns_to_exact_stock_with_backup_and_no_boot_write(self):
        before = raw_fixture(patcher.build_patch(self.original, dashboard='purple_drift', usb_1ms=True))
        device = FakeDevice(before)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            installer.transfer(device, self.original, self.original, directory, lambda *_: None)
            self.assertEqual((directory / 'avant-raw.bin').read_bytes(), before)
        self.assertEqual(device.raw[:installer.APP], before[:installer.APP])
        self.assertEqual(device.raw[installer.APP:installer.APP + len(self.original)], self.original)
        self.assertTrue(all(offset >= installer.APP for offset in device.writes))
        _, offsets, state = installer.plan_transfer(bytes(device.raw), self.original, self.original)
        self.assertEqual(offsets, ())
        self.assertEqual(state, 'original-2.0.5')

    @unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_120'), 'Optional official 1.2.0 fixture')
    def test_old_version_is_accepted_only_for_exact_official_target(self):
        old = Path(os.environ['DDF350_OFFICIAL_120']).read_bytes()
        self.assertEqual(patcher.sha256(old), installer.OFFICIAL_120_HASH)
        before = raw_fixture(old)
        after, offsets, state = installer.plan_transfer(before, self.original, self.original)
        self.assertEqual(state, 'original-1.2.0')
        self.assertTrue(offsets)
        self.assertEqual(after[installer.APP:installer.APP + len(self.original)], self.original)
        self.assertEqual(after[:installer.APP], before[:installer.APP])
        modified = patcher.build_patch(self.original, usb_1ms=True)
        with self.assertRaisesRegex(ValueError, 'Firmware installé inconnu'):
            installer.plan_transfer(before, modified, self.original)
        changed = bytearray(before)
        changed[installer.APP + 0x4000] ^= 1
        with self.assertRaisesRegex(ValueError, 'Firmware installé inconnu'):
            installer.plan_transfer(bytes(changed), self.original, self.original)


if __name__ == '__main__':
    unittest.main()
