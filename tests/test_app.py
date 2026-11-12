"""Desktop workflow checks. All HID readers and firmware operations are mocked."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HAVE_TK = importlib.util.find_spec("tkinter") is not None
if HAVE_TK:
    import tkinter as tk
    import app
    from pc import ddf350_hid as hid


@unittest.skipUnless(HAVE_TK, "Tkinter not installed")
class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.ui = app.Application(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.ui.busy = False
        if not self.ui.closed:
            self.ui.close()

    def test_three_choices_do_not_open_a_reader(self):
        with mock.patch.object(hid.Reader, "start", side_effect=AssertionError("Unexpected USB reader")):
            for choice in ("original", "ch1234", "ch123456"):
                self.ui.select_dashboard(choice)
                self.assertEqual(self.ui.dashboard.get(), choice)
            self.assertIsNone(self.ui.viewer)

    def test_selection_is_captured_and_controls_lock_during_preparation(self):
        release = threading.Event()
        finished = threading.Event()
        calls = []

        def prepare(*args):
            calls.append(args)
            if not release.wait(3):
                raise TimeoutError("test worker not released")
            finished.set()
            return {"file_written": True}

        self.ui.source.set("original.bin")
        self.ui.dashboard.set("ch123456")
        self.ui.fast.set(False)
        try:
            with mock.patch.object(app.filedialog, "asksaveasfilename", return_value="output.bin"), \
                 mock.patch.object(app, "prepare_file", side_effect=prepare):
                self.ui.create()
                self.assertTrue(self.ui.busy)
                self.assertTrue(all(str(c.cget("state")) == "disabled" for c in self.ui.controls))
                self.ui.select_dashboard("original")
                self.assertEqual(self.ui.dashboard.get(), "ch123456")
                release.set()
                self.assertTrue(finished.wait(3))
                deadline = time.monotonic() + 3
                while self.ui.events.empty() and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.ui.poll()
            self.assertEqual(calls, [("original.bin", "output.bin", "ch123456", False)])
            self.assertFalse(self.ui.busy)
            self.assertIn("créé et vérifié", self.ui.status.get())
        finally:
            release.set()

    def test_file_rejection_does_not_claim_success(self):
        self.ui.busy = True
        self.ui.events.put(("error", "Original firmware SHA-256 does not match", None))
        with mock.patch.object(app.messagebox, "showerror") as error:
            self.ui.poll()
        error.assert_called_once()
        self.assertFalse(self.ui.busy)
        self.assertNotIn("créé et vérifié", self.ui.status.get())

    def test_embedded_reader_close_keeps_main_window_and_cancels_callback(self):
        with mock.patch.object(hid.Reader, "start") as start, \
             mock.patch.object(hid.Reader, "request_stop") as stop:
            self.ui.open_reader()
            viewer = self.ui.viewer
            start.assert_called_once()
            self.assertIs(viewer.root.master, self.root)
            self.assertFalse(viewer.owns_root)
            callback = viewer.poll_id
            self.assertIn(callback, self.root.tk.call("after", "info"))
            viewer.close()
            self.assertNotIn(callback, self.root.tk.call("after", "info"))
            self.assertEqual(self.root.winfo_exists(), 1)
            stop.assert_called_once()

    def test_failed_build_cannot_reach_output_write(self):
        with mock.patch.object(app.patcher, "read_regular_file", return_value=b"input"), \
             mock.patch.object(app.patcher, "build_patch", side_effect=app.patcher.PatchError("bad image")), \
             mock.patch.object(app.patcher, "write_new_output") as writer:
            with self.assertRaises(app.patcher.PatchError):
                app.prepare_file("source.bin", "output.bin", "ch123456", True)
        writer.assert_not_called()

    def test_unconfirmed_radio_version_opens_guidance_before_file_creation(self):
        self.ui.version_confirmed = False
        with mock.patch.object(self.ui, "show_compatibility") as guidance, \
             mock.patch.object(app.filedialog, "asksaveasfilename") as save:
            self.ui.create()
        guidance.assert_called_once()
        save.assert_not_called()

    def test_unverified_download_cannot_be_selected(self):
        self.ui.source.set("")
        with mock.patch.object(app.patcher, "read_regular_file", return_value=b"wrong file"), \
             mock.patch.object(app.filedialog, "askopenfilename", return_value="wrong.bin"), \
             mock.patch.object(app.messagebox, "showerror") as error:
            self.ui.browse()
        error.assert_called_once()
        self.assertEqual(self.ui.source.get(), "")


if __name__ == "__main__":
    unittest.main()
