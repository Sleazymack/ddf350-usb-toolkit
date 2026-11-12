"""File-boundary tests; no firmware input, device, network or admin access."""
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import patch_firmware as patcher


class LocalFileBoundaryTests(unittest.TestCase):
    def test_fixed_drive_is_required_for_input_and_output_on_windows(self):
        local = Path("offline-fixture.bin")
        with mock.patch.object(patcher, "IS_WINDOWS", True):
            for purpose in ("Input", "Output"):
                for drive_type in (0, 1, 2, 4, 5, 6):
                    with self.subTest(purpose=purpose, drive_type=drive_type):
                        with mock.patch.object(patcher, "_windows_drive_type", return_value=drive_type):
                            with self.assertRaises(patcher.PatchError):
                                patcher._check_local_volume(local, purpose)
                with mock.patch.object(patcher, "_windows_drive_type", return_value=3) as query:
                    patcher._check_local_volume(local, purpose)
                    self.assertTrue(query.call_args.args[0])

    def test_non_windows_does_not_load_windows_adapter(self):
        with mock.patch.object(patcher, "IS_WINDOWS", False), \
             mock.patch.object(patcher, "_windows_drive_type", side_effect=AssertionError("Windows API")):
            patcher._check_local_volume(Path("offline-fixture.bin"), "Output")

    def test_input_on_removable_drive_is_refused_before_open(self):
        with mock.patch.object(patcher, "IS_WINDOWS", True), \
             mock.patch.object(patcher, "_windows_drive_type", return_value=2), \
             mock.patch.object(Path, "lstat", side_effect=AssertionError("lstat after refused volume")), \
             mock.patch.object(patcher.os, "open", side_effect=AssertionError("input opened")):
            with self.assertRaises(patcher.PatchError):
                patcher.read_regular_file("offline-fixture.bin")

    def test_output_on_network_drive_is_refused_before_creation(self):
        with mock.patch.object(patcher, "IS_WINDOWS", True), \
             mock.patch.object(patcher, "_windows_drive_type", return_value=4), \
             mock.patch.object(patcher, "inspect_image", return_value={"recognized": True}), \
             mock.patch.object(Path, "open", side_effect=AssertionError("output created")):
            with self.assertRaises(patcher.PatchError):
                patcher.write_new_output("new-offline-fixture.bin", b"mock-only", source="original-fixture.bin")

    def test_non_regular_inputs_are_refused_without_opening(self):
        with mock.patch.object(patcher, "_check_local_volume"), \
             mock.patch.object(patcher.os, "open", side_effect=AssertionError("special file opened")):
            for mode in (stat.S_IFDIR, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFLNK):
                with self.subTest(mode=mode), \
                     mock.patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=mode)):
                    with self.assertRaises(patcher.PatchError):
                        patcher.read_regular_file("offline-fixture.bin")

    def test_unexpected_size_is_refused_before_read(self):
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.fileno.return_value = 123
        stream.read.side_effect = AssertionError("unexpected-size data read")
        with mock.patch.object(patcher, "_check_local_volume"), \
             mock.patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG)), \
             mock.patch.object(patcher.os, "open", return_value=123), \
             mock.patch.object(patcher.os, "fdopen", return_value=stream), \
             mock.patch.object(patcher.os, "fstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_size=patcher.MAX_IMAGE_SIZE + 1)):
            with self.assertRaises(patcher.PatchError):
                patcher.read_regular_file("offline-fixture.bin")
        stream.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
