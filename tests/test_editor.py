"""Dashboard editor regression checks with hidden Tk and temporary JSON only.

No real firmware, radio, USB reader, desktop capture or native dialog is used.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HAVE_TK = importlib.util.find_spec("tkinter") is not None
if HAVE_TK:
    import tkinter as tk
    import dashboard_custom
    import editor
    import patch_firmware


ONE_GAUGE = {
    "schema": 1,
    "background": "#162d46",
    "widgets": [{"id": "g1", "channel": 1, "kind": "bar", "col": 0,
                 "row": 0, "color": "#55b8f0"}],
}


@unittest.skipUnless(HAVE_TK, "Tkinter not installed")
class DashboardEditorTests(unittest.TestCase):
    def setUp(self):
        # A failed import or a future editor regression must never turn a
        # layout test into a firmware operation.
        for name in ("read_regular_file", "build_patch", "write_new_output"):
            forbidden = mock.patch.object(
                patch_firmware, name, side_effect=AssertionError("Unexpected firmware operation"))
            forbidden.start()
            self.addCleanup(forbidden.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.changes = []
        self.ui = editor.DashboardEditor(self.root, onchange=self.changes.append)
        self.ui.pack()
        self.root.update_idletasks()

    def event_at(self, x, y):
        """Translate an illustrative screen point into canvas coordinates."""
        return SimpleNamespace(x=self.ui.origin[0] + x * self.ui.scale,
                               y=self.ui.origin[1] + y * self.ui.scale)

    def test_default_geometry_and_colors_follow_backend_contract(self):
        self.assertEqual(self.ui.get_layout(), dashboard_custom.validate_layout(editor.DEFAULT_LAYOUT))
        self.assertEqual(editor.widget_bounds({"kind": "bar", "col": 0, "row": 0}),
                         (20, 200, 163, 225))
        self.assertEqual(editor.widget_bounds({"kind": "semicircle", "col": 4, "row": 2}),
                         (163, 250, 235, 300))
        self.assertEqual(editor.track_color("#55b8f0", "#162d46"),
                         dashboard_custom.track_color("#55b8f0", "#162d46"))
        for widget in self.ui.get_layout()["widgets"]:
            with self.subTest(channel=widget["channel"]):
                self.assertEqual(editor._widget_parts(widget), dashboard_custom.widget_parts(widget))
        self.assertEqual(self.changes, [])

    def test_get_set_and_callback_keep_independent_copies(self):
        result = self.ui.get_layout()
        result["widgets"][0]["channel"] = 6
        self.assertEqual(self.ui.get_layout()["widgets"][0]["channel"], 1)
        supplied = copy.deepcopy(ONE_GAUGE)
        self.ui.set_layout(supplied)
        supplied["widgets"][0]["channel"] = 6
        self.assertEqual(self.ui.get_layout()["widgets"][0]["channel"], 1)
        self.assertEqual(len(self.changes), 1)
        self.changes[0]["widgets"][0]["color"] = "#000000"
        self.assertEqual(self.ui.get_layout()["widgets"][0]["color"], "#55b8f0")
        self.ui.set_layout(ONE_GAUGE)
        self.assertEqual(len(self.changes), 1, "Setting the same layout is not a change")

    def test_invalid_set_arrows_and_duplicate_channel_are_atomic(self):
        original = self.ui.get_layout()
        overlap = copy.deepcopy(original)
        overlap["widgets"][0]["col"] = 2
        with self.assertRaises(ValueError):
            self.ui.set_layout(overlap)
        self.assertFalse(self.ui.move_selected(-1, 0), "Out-of-bounds move must fail")
        self.assertFalse(self.ui.move_selected(1, 0), "Overlapping move must fail")
        self.ui.channel.set("CH2")
        self.ui._change_channel(None)
        self.assertEqual(self.ui.channel.get(), "CH1", "Rejected control value is restored")
        self.assertEqual(self.ui.get_layout(), original)
        self.assertEqual(self.changes, [])

    def test_theme_changes_only_colors_and_color_cancel_is_noop(self):
        original = self.ui.get_layout()
        self.ui.apply_theme("Menthe")
        themed = self.ui.get_layout()
        self.assertEqual(themed["background"], "#132b29")
        for before, after in zip(original["widgets"], themed["widgets"]):
            self.assertEqual({key: value for key, value in {'zone':'B',**before}.items() if key != "color"},
                             {key: value for key, value in after.items() if key != "color"})
        self.assertEqual(len(self.changes), 1)
        with mock.patch.object(editor.colorchooser, "askcolor", return_value=((1, 2, 3), "#010203")):
            self.ui.choose_widget_color()
        self.assertEqual(self.ui.get_layout()["widgets"][0]["color"], "#010203")
        before_cancel = self.ui.get_layout()
        before_count = len(self.changes)
        with mock.patch.object(editor.colorchooser, "askcolor", return_value=(None, None)):
            self.ui.choose_background()
        self.assertEqual(self.ui.get_layout(), before_cancel)
        self.assertEqual(len(self.changes), before_count)

    def test_valid_drag_snaps_and_commits_once_on_release(self):
        self.ui.set_layout(ONE_GAUGE)
        self.changes.clear()
        self.ui._press(self.event_at(35, 210))
        target = self.event_at(35 + 215 / 6, 235)
        self.ui._motion(target)
        self.assertEqual((self.ui._proposal["col"], self.ui._proposal["row"]), (1, 1))
        self.assertIsNone(self.ui._proposal_error)
        self.assertEqual(self.ui.get_layout(), dashboard_custom.validate_layout(ONE_GAUGE))
        self.assertEqual(self.changes, [], "Preview must not notify the application")
        self.ui._release(target)
        placed = self.ui.get_layout()["widgets"][0]
        self.assertEqual((placed["col"], placed["row"]), (1, 1))
        self.assertEqual(len(self.changes), 1)
        self.assertIsNone(self.ui._drag)

    def test_invalid_drag_is_red_and_release_or_escape_preserves_layout(self):
        original = self.ui.get_layout()
        self.ui._press(self.event_at(35, 210))
        self.ui._motion(self.event_at(-100, 150))
        self.assertIsNotNone(self.ui._proposal_error)
        outlines = [self.ui.canvas.itemcget(item, "outline")
                    for item in self.ui.canvas.find_all()
                    if self.ui.canvas.type(item) == "rectangle"]
        self.assertIn(editor.ERROR, outlines)
        self.ui._release(self.event_at(-100, 150))
        self.assertEqual(self.ui.get_layout(), original)
        self.ui._press(self.event_at(35, 210))
        self.ui._motion(self.event_at(35, 235))  # Collides with the next bar.
        self.assertIsNotNone(self.ui._proposal_error)
        self.ui._cancel_drag()
        self.assertEqual(self.ui.get_layout(), original)
        self.assertIsNone(self.ui._drag)
        self.assertEqual(self.changes, [])

    def test_add_delete_and_minimum_one_gauge(self):
        self.assertFalse(self.ui.add_widget("bar"), "All six channels are already used")
        self.ui.set_layout(ONE_GAUGE)
        self.assertFalse(self.ui.delete_selected(), "The final gauge must remain")
        self.assertTrue(self.ui.add_widget("semicircle"))
        widgets = self.ui.get_layout()["widgets"]
        self.assertEqual(len(widgets), 2)
        added = next(widget for widget in widgets if widget["channel"] == 2)
        self.assertEqual((added["kind"], added["col"], added["row"]), ("semicircle", 4, 0))
        self.assertTrue(self.ui.delete_selected())
        self.assertEqual(self.ui.get_layout(), dashboard_custom.validate_layout(ONE_GAUGE))

    def test_json_round_trip_and_existing_export_is_preserved(self):
        self.ui.set_layout(ONE_GAUGE)
        with tempfile.TemporaryDirectory(prefix="ddf-editor-test-") as directory:
            output = Path(directory) / "layout.json"
            with mock.patch.object(editor.filedialog, "asksaveasfilename", return_value=str(output)):
                self.ui.export_json()
            original_bytes = output.read_bytes()
            self.assertEqual(json.loads(original_bytes), self.ui.get_layout())
            self.ui.apply_theme("Rouge nuit")
            with mock.patch.object(editor.filedialog, "asksaveasfilename", return_value=str(output)), \
                 mock.patch.object(editor.messagebox, "showerror") as notice:
                self.ui.export_json()
            notice.assert_called_once()
            self.assertEqual(output.read_bytes(), original_bytes)
            with mock.patch.object(editor.filedialog, "askopenfilename", return_value=str(output)):
                self.ui.import_json()
            self.assertEqual(self.ui.get_layout(), dashboard_custom.validate_layout(ONE_GAUGE))

    def test_bad_or_oversized_json_preserves_current_layout(self):
        original = self.ui.get_layout()
        cases = {
            "missing-fields": b'{"schema":1}',
            "duplicate-key": b'{"schema":1,"schema":1}',
            "too-large": b" " * (dashboard_custom.LAYOUT_MAX_BYTES + 1),
            "wrong-encoding": b"\xff\xfe\xff",
        }
        with tempfile.TemporaryDirectory(prefix="ddf-editor-test-") as directory:
            for name, content in cases.items():
                with self.subTest(case=name):
                    source = Path(directory) / (name + ".json")
                    source.write_bytes(content)
                    with mock.patch.object(editor.filedialog, "askopenfilename", return_value=str(source)), \
                         mock.patch.object(editor.messagebox, "showerror") as notice:
                        self.ui.import_json()
                    notice.assert_called_once()
                    self.assertEqual(self.ui.get_layout(), original)
                    self.assertEqual(self.changes, [])

    def test_removable_volume_is_refused_before_file_access(self):
        with tempfile.TemporaryDirectory(prefix="ddf-editor-test-") as directory:
            filename = str(Path(directory) / "layout.json")
            with mock.patch.object(patch_firmware, "IS_WINDOWS", True), \
                 mock.patch.object(patch_firmware, "_windows_drive_type", return_value=2), \
                 mock.patch.object(editor.messagebox, "showerror") as notice:
                with mock.patch.object(editor.filedialog, "asksaveasfilename", return_value=filename), \
                     mock.patch.object(Path, "open", side_effect=AssertionError("Unexpected write")) as writer:
                    self.ui.export_json()
                writer.assert_not_called()
                with mock.patch.object(editor.filedialog, "askopenfilename", return_value=filename), \
                     mock.patch.object(patch_firmware.os, "open", side_effect=AssertionError("Unexpected read")) as reader:
                    self.ui.import_json()
                reader.assert_not_called()
                self.assertEqual(notice.call_count, 2)
            self.assertFalse(Path(filename).exists())
            self.assertEqual(self.changes, [])

    def test_device_nonlocal_and_wrong_extension_exports_are_refused(self):
        for filename in ("NUL.json", "C:/test/layout.json:stream", "//server/share/layout.json"):
            with self.subTest(filename=filename), \
                 mock.patch.object(editor.filedialog, "asksaveasfilename", return_value=filename), \
                 mock.patch.object(Path, "open", side_effect=AssertionError("Unexpected write")) as writer, \
                 mock.patch.object(editor.messagebox, "showerror") as notice:
                self.ui.export_json()
                writer.assert_not_called()
                notice.assert_called_once()
        with tempfile.TemporaryDirectory(prefix="ddf-editor-test-") as directory:
            filename = str(Path(directory) / "layout.txt")
            with mock.patch.object(editor.filedialog, "asksaveasfilename", return_value=filename), \
                 mock.patch.object(editor.messagebox, "showerror") as notice:
                self.ui.export_json()
            notice.assert_called_once()
            self.assertFalse(Path(filename).exists())

    def test_cancelled_file_dialogs_do_not_access_files(self):
        with mock.patch.object(editor.filedialog, "askopenfilename", return_value=""), \
             mock.patch.object(editor.filedialog, "asksaveasfilename", return_value=""), \
             mock.patch.object(patch_firmware, "read_layout_file") as reader, \
             mock.patch.object(patch_firmware, "validate_local_path") as validate:
            self.ui.import_json()
            self.ui.export_json()
        reader.assert_not_called()
        validate.assert_not_called()
        self.assertEqual(self.changes, [])


if __name__ == "__main__":
    unittest.main()
