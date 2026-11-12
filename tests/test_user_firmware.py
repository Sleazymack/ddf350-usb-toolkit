"""User-supplied input, official link, and elevated-worker handoff; no USB."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import installer
import patch_firmware as p
import tkinter as tk
import wizard


class FirmwareInputTests(unittest.TestCase):
    def test_packaged_app_without_bundled_image_ignores_developer_override(self):
        with mock.patch.object(sys, 'frozen', True, create=True), \
             mock.patch.object(sys, '_MEIPASS', 'unused', create=True), \
             mock.patch.dict(os.environ, {'DDF350_OFFICIAL_FIRMWARE': 'unused.bin'}), \
             mock.patch.object(p, 'read_regular_file') as read:
            self.assertIsNone(app.find_official_firmware())
        read.assert_not_called()

    def test_corrupt_embedded_image_is_rejected_instead_of_using_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'firmware'/'DDF-2.0.5.bin';path.parent.mkdir();path.write_bytes(b'wrong file')
            with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'_MEIPASS',folder,create=True), \
                 mock.patch.dict(os.environ,{'DDF350_OFFICIAL_FIRMWARE':'different-file.bin'}):
                with self.assertRaises(p.PatchError):app.find_official_firmware()

    @unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official input not supplied')
    def test_exact_embedded_image_is_selected_and_verified_without_external_input(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();p._require_original(original)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'firmware'/'DDF-2.0.5.bin';path.parent.mkdir();path.write_bytes(original)
            with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'_MEIPASS',folder,create=True), \
                 mock.patch.dict(os.environ,{'DDF350_OFFICIAL_FIRMWARE':'ignored-file.bin'}):
                self.assertEqual(Path(app.find_official_firmware()),path)

    def test_worker_rejects_missing_and_invalid_local_snapshot_before_usb(self):
        for payload in (None, b'wrong official image'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); job=root/'job'; job.mkdir()
                if payload is not None:(job/'original.bin').write_bytes(payload)
                with mock.patch.object(installer,'runs_root',return_value=root), \
                     mock.patch.object(installer,'discover',side_effect=AssertionError('USB must not be opened')) as discover:
                    with self.assertRaises((OSError,ValueError)):
                        installer.run_job(job)
                discover.assert_not_called()

    def test_cli_worker_uses_job_snapshot_instead_of_environment(self):
        with mock.patch.object(installer,'run_job') as worker, \
             mock.patch.object(app,'find_official_firmware',side_effect=AssertionError('Not a worker input')):
            app.main(['--install-job','local-job'])
        worker.assert_called_once_with('local-job')


class FirmwarePageTests(unittest.TestCase):
    def setUp(self):
        self.guard=mock.patch.object(app,'find_official_firmware',return_value=None)
        self.guard.start(); self.addCleanup(self.guard.stop)
        self.root=tk.Tk();self.root.attributes('-alpha',0)
        self.ui=wizard.Wizard(self.root)

    def tearDown(self):
        self.ui.busy=False; self.ui.close()

    def test_version_confirmation_requires_local_file_and_official_link_is_explicit(self):
        self.ui.confirm_version();self.root.update()
        self.assertEqual(self.ui.step,1)
        self.assertEqual(str(self.ui.forward.cget('state')),'disabled')
        self.ui.next();self.assertEqual(self.ui.step,1)
        with mock.patch.object(app.webbrowser,'open') as browser:
            self.ui.download_button.invoke()
        browser.assert_called_once_with('https://www.dumborc.com/?page_id=930')
        for widget in (self.ui.download_button,self.ui.firmware_button,self.ui.forward):
            bottom=widget.winfo_rooty()-self.root.winfo_rooty()+widget.winfo_height()
            self.assertLessEqual(bottom,self.root.winfo_height())

    def test_cancel_does_not_advance_or_validate_file(self):
        self.ui.confirm_version()
        with mock.patch.object(app.filedialog,'askopenfilename',return_value=''), \
             mock.patch.object(p,'read_regular_file') as read:
            self.ui.firmware_button.invoke()
        read.assert_not_called();self.assertFalse(self.ui.source.get())
        self.assertEqual(str(self.ui.forward.cget('state')),'disabled')

    def test_verified_selection_enables_continue_and_keeps_dashboard_workflow(self):
        self.ui.confirm_version()
        with mock.patch.object(app.filedialog,'askopenfilename',return_value='selected.bin'), \
             mock.patch.object(p,'read_regular_file',return_value=b'fixture'), \
             mock.patch.object(p,'_require_original') as validate, \
             mock.patch.object(app.messagebox,'showinfo'):
            self.ui.firmware_button.invoke()
        validate.assert_called_once_with(b'fixture')
        self.assertEqual(self.ui.source.get(),'selected.bin')
        self.assertEqual(str(self.ui.forward.cget('state')),'normal')
        self.ui.next();self.assertEqual(self.ui.step,2)

    @unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official input not supplied')
    def test_complete_custom_dashboard_workflow_reaches_protected_install_from_same_window(self):
        source=os.environ['DDF350_OFFICIAL_FIRMWARE']
        self.ui.confirm_version()
        with mock.patch.object(app.filedialog,'askopenfilename',return_value=source),mock.patch.object(app.messagebox,'showinfo'):
            self.ui.firmware_button.invoke()
        self.ui.forward.invoke();self.assertEqual(self.ui.step,2)
        self.ui.choose_custom();self.assertIsNotNone(self.ui.inline_editor)
        self.ui.forward.invoke();self.assertEqual(self.ui.step,4)
        self.assertIsNone(self.ui.target)
        self.ui.forward.invoke();self.assertEqual(self.ui.step,5)
        self.assertTrue(p.inspect_image(self.ui.target)['recognized'])
        identity={'mock':'no physical radio'}
        self.ui.events.put(('detected',identity,None));self.ui.poll()
        self.ui.forward.invoke();self.assertEqual(self.ui.step,6)
        ready=threading.Event()
        def launch(directory):ready.set();return 123
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(installer,'runs_root',return_value=Path(folder)), \
             mock.patch.object(installer,'launch_elevated',side_effect=launch):
            self.ui.forward.invoke();self.assertTrue(ready.wait(3))
            job=self.ui.job_directory
            self.assertEqual((job/'target.bin').read_bytes(),self.ui.target)
            self.assertEqual((job/'original.bin').read_bytes(),Path(source).read_bytes())
            self.assertEqual(json.loads((job/'job.json').read_text())['identity'],identity)

    @unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official input not supplied')
    def test_install_stages_verified_original_for_elevated_worker(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        p._require_original(original)
        ready=threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'download.bin';source.write_bytes(original)
            self.ui.source.set(str(source));self.ui.target=p.build_patch(original)
            self.ui.identity={'mock':'no physical radio'};self.ui.step=6;self.ui.render()
            def launch(directory):ready.set();return 123
            with mock.patch.object(installer,'runs_root',return_value=root/'jobs'), \
                 mock.patch.object(installer,'launch_elevated',side_effect=launch):
                self.ui.install();self.assertTrue(ready.wait(3))
            job=self.ui.job_directory
            self.assertEqual((job/'original.bin').read_bytes(),original)
            self.assertEqual((job/'target.bin').read_bytes(),self.ui.target)
            self.assertEqual(json.loads((job/'job.json').read_text())['target_sha256'],p.sha256(self.ui.target))
            # Exercise the real worker's input boundary; stop before any USB call.
            with mock.patch.object(installer,'runs_root',return_value=root/'jobs'), \
                 mock.patch.object(installer,'discover',side_effect=RuntimeError('stop before hardware')) as discover:
                with self.assertRaisesRegex(RuntimeError,'stop before hardware'):installer.run_job(job)
            discover.assert_called_once()


if __name__=='__main__':unittest.main()
