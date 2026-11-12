"""Portable, independent checks; original firmware is supplied by the user.

Run: python -m unittest discover -s tests -v
Optional integration: set DDF350_OFFICIAL_FIRMWARE to the supported local file.
All generated firmware exists only in TemporaryDirectory outside this repository.
No device, flashing tool, network request, or admin command is used.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import patch_firmware as patcher

OFFICIAL_SHA = "06c47e22049f0ec91823156b3a1afb997dfe31309d06c493aab08426d2866bbc"
CLOCK_SHA = "b122be6391d42354bff9d4e146526dcca323d277abecc1a999f539276af6902c"
FAST_SHA = "9afd478afc6085b48435816273f844ff277facbb48d7116f5bfe84daa0cbf250"
OFFICIAL_SIZE = 626956


def sha(data):
    return hashlib.sha256(data).hexdigest()


def cli(*args, optimized=False):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend([str(ROOT / "patch_firmware.py"), *map(str, args)])
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


class InputGuardTests(unittest.TestCase):
    def test_arbitrary_content_cannot_be_patched_or_reverted(self):
        for data in (b"", b"not firmware", b"\0" * OFFICIAL_SIZE,
                     b"\xff" * OFFICIAL_SIZE, b"\0" * (OFFICIAL_SIZE + 276)):
            for operation in (patcher.build_patch, patcher.revert_patch):
                with self.subTest(size=len(data), operation=operation.__name__):
                    with self.assertRaises(ValueError):
                        operation(data)

    def test_windows_devices_unc_and_alternate_streams_are_rejected(self):
        unsafe = ["NUL", "CON", "PRN", "AUX", "COM1", "COM9", "LPT1", "LPT9",
                  "COM1.bin", "NUL.txt", "LPT1.log", "con.bin", "COM¹.txt",
                  "firmware.bin:payload", "C:\\firmware.bin:stream", "bad\0name",
                  "\\\\.\\PhysicalDrive0", "\\\\.\\COM1", "\\\\?\\C:\\firmware.bin",
                  "\\\\server\\share\\firmware.bin", "//server/share/firmware.bin"]
        # Pure path validation, not attempts to open a real device.
        with mock.patch("builtins.open", side_effect=AssertionError("path validation must not open files")), \
             mock.patch("os.open", side_effect=AssertionError("path validation must not open files")):
            for path in unsafe:
                for output in (False, True):
                    with self.subTest(path=path, output=output):
                        with self.assertRaises(ValueError):
                            patcher.validate_local_path(path, output=output)

    def test_cli_rejects_invalid_input_with_and_without_optimization(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-test-") as name:
            root = Path(name)
            source = root / "invalid.bin"
            source.write_bytes(b"unsupported image")
            for optimized in (False, True):
                target = root / f"must-not-exist-{optimized}.bin"
                result = cli("patch", source, "--output", target, optimized=optimized)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), b"unsupported image")


@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class FirmwareIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if len(cls.original) != OFFICIAL_SIZE or sha(cls.original) != OFFICIAL_SHA:
            raise ValueError("DDF350_OFFICIAL_FIRMWARE must be the exact supported official image")
        cls.clock = patcher.build_patch(cls.original)
        cls.fast = patcher.build_patch(cls.original, usb_1ms=True)

    def test_exact_clock_only_diff(self):
        expected = bytearray(self.original)
        self.assertEqual(expected[0x21B0E], 0x24)
        expected[0x21B0E] = 0x1C
        self.assertEqual(self.clock, bytes(expected))
        self.assertEqual(sha(self.clock), CLOCK_SHA)

    def test_exact_fast_hash_and_all_preexisting_bytes(self):
        self.assertEqual(sha(self.fast), FAST_SHA)
        self.assertEqual(len(self.fast), OFFICIAL_SIZE + 276)
        permitted = set()
        for start, size in ((0x21B0E, 1), (0x96F23, 1), (0x2C992, 2),
                            (0x2C986, 12), (0x2C8A2, 6)):
            permitted.update(range(start, start + size))
        changes = {i for i in range(OFFICIAL_SIZE) if self.original[i] != self.fast[i]}
        self.assertTrue(changes)
        self.assertTrue(changes <= permitted, f"undeclared changed bytes: {sorted(changes - permitted)}")
        self.assertEqual(self.fast[0x21B0E], 0x1C)
        self.assertEqual(self.fast[0x96F23], 1)
        self.assertEqual(self.fast[0x96F2A], self.original[0x96F2A])
        self.assertEqual(self.fast[0x96F2A], 20)
        self.assertEqual(self.fast[0x2C992:0x2C994], b"\x01\x20")

    def test_revert_is_exact_for_both_variants(self):
        for data in (self.clock, self.fast):
            with self.subTest(hash=sha(data)):
                restored = patcher.revert_patch(data)
                self.assertEqual(restored, self.original)
                self.assertEqual(sha(restored), OFFICIAL_SHA)

    def test_guards_reject_every_variant_of_wrong_input(self):
        for data in (self.clock, self.fast, self.original[:-1], self.original + b"\0"):
            for usb_1ms in (False, True):
                with self.subTest(size=len(data), usb_1ms=usb_1ms):
                    with self.assertRaises(ValueError):
                        patcher.build_patch(data, usb_1ms=usb_1ms)
        for data in (self.original, self.clock, self.fast):
            for index in (0, 0x21B0E, 0x2C8A2, len(data) - 1):
                changed = bytearray(data)
                changed[index] ^= 1
                with self.subTest(hash=sha(data), index=hex(index)):
                    with self.assertRaises(ValueError):
                        patcher.build_patch(bytes(changed))
                    with self.assertRaises(ValueError):
                        patcher.revert_patch(bytes(changed))

    def test_cli_roundtrip_and_dry_run_with_python_optimization(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-test-") as name:
            root = Path(name)
            source = root / "original.bin"
            source.write_bytes(self.original)
            for optimized in (False, True):
                for fast in (False, True):
                    label = f"{optimized}-{fast}"
                    target = root / f"patched-{label}.bin"
                    restored = root / f"restored-{label}.bin"
                    flags = ["--usb-1ms"] if fast else []
                    dry = cli("patch", source, "--output", target, *flags, "--dry-run", optimized=optimized)
                    self.assertEqual(dry.returncode, 0, dry.stderr)
                    self.assertFalse(target.exists())
                    applied = cli("patch", source, "--output", target, *flags, optimized=optimized)
                    self.assertEqual(applied.returncode, 0, applied.stderr)
                    self.assertEqual(target.read_bytes(), self.fast if fast else self.clock)
                    dry_revert = cli("revert", target, "--output", restored, "--dry-run", optimized=optimized)
                    self.assertEqual(dry_revert.returncode, 0, dry_revert.stderr)
                    self.assertFalse(restored.exists())
                    reverted = cli("revert", target, "--output", restored, optimized=optimized)
                    self.assertEqual(reverted.returncode, 0, reverted.stderr)
                    self.assertEqual(restored.read_bytes(), self.original)
            self.assertEqual(source.read_bytes(), self.original)

    def test_cli_never_overwrites_output_input_or_hardlink(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-test-") as name:
            root = Path(name)
            source = root / "original.bin"
            source.write_bytes(self.original)
            existing = root / "existing.bin"
            existing.write_bytes(b"keep this exact content")
            linked = root / "hardlink.bin"
            os.link(source, linked)
            for target in (existing, source, linked, root):
                before = target.read_bytes() if target.is_file() else None
                result = cli("patch", source, "--output", target)
                self.assertNotEqual(result.returncode, 0)
                if before is not None:
                    self.assertEqual(target.read_bytes(), before)
            self.assertEqual(source.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
