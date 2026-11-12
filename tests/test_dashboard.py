"""Independent dashboard-selection checks; no device access or bundled firmware.

The optional ARM tests execute two existing display functions with graphics calls
replaced by observers. They verify values/side effects, not a rendered screen,
whole-menu lifecycle, USB stability, or firmware installation.
"""
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import patch_firmware as patcher
from test_patch_firmware import cli

try:
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS,
                         UC_HOOK_CODE, UC_HOOK_MEM_WRITE)
    from unicorn.arm_const import (
        UC_CPU_ARM_CORTEX_M4, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
        UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
        UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
    )
    HAVE_ARM = True
except ImportError:
    HAVE_ARM = False

SOURCE_SHA = "06c47e22049f0ec91823156b3a1afb997dfe31309d06c493aab08426d2866bbc"
EXPECTED = {
    (False, "original"): "b122be6391d42354bff9d4e146526dcca323d277abecc1a999f539276af6902c",
    (True, "original"): "9afd478afc6085b48435816273f844ff277facbb48d7116f5bfe84daa0cbf250",
    (False, "ch1234"): "ab1e07209af3ded75a70f5567dc598ba33ec05de9cd771edee27448b9f8bf67e",
    (True, "ch1234"): "3f67d80255dca8fe7c3544ad7417bc88b4067f3bce01e4899913187e6f1095de",
}
DISPLAY_CHANGES = {0x3BF4: (0x14, 0x0C), 0x3CCC: (0x18, 0x10),
                   0x57C5A: (ord("5"), ord("3")), 0x57C62: (ord("6"), ord("4"))}
BASE, RAM, STACK, STOP = 0x08005000, 0x20000000, 0x20017000, 0x10000000
ROWS = (
    {"start": 0x3B3C, "end": 0x3BF0, "channel": 3, "old_channel": 5,
     "cache": RAM + 0x724, "last": RAM + 0x728, "label": RAM + 0x678, "bar": RAM + 0x68C},
    {"start": 0x3C14, "end": 0x3CC8, "channel": 4, "old_channel": 6,
     "cache": RAM + 0x72C, "last": RAM + 0x730, "label": RAM + 0x680, "bar": RAM + 0x690},
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def signed(value):
    return struct.unpack("<i", struct.pack("<I", value & 0xFFFFFFFF))[0]


class DashboardArgumentTests(unittest.TestCase):
    def test_invalid_cli_choice_rejected_before_input_read(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-dashboard-") as name:
            missing = Path(name) / "not-present.bin"
            output = Path(name) / "must-not-exist.bin"
            for optimized in (False, True):
                result = cli("patch", missing, "--dashboard", "other", "--output", output,
                             optimized=optimized)
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid choice", result.stderr)
                self.assertFalse(output.exists())


@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class DashboardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if len(cls.original) != 626956 or digest(cls.original) != SOURCE_SHA:
            raise ValueError("The exact supported official input is required")
        cls.variants = {(fast, dashboard): patcher.build_patch(cls.original, usb_1ms=fast,
                                                              dashboard=dashboard)
                        for fast in (False, True) for dashboard in ("original", "ch1234")}

    def test_original_dashboard_remains_default(self):
        for fast in (False, True):
            self.assertEqual(patcher.build_patch(self.original, usb_1ms=fast),
                             self.variants[(fast, "original")])

    def test_four_display_bytes_only_all_other_bytes_preserved(self):
        for fast in (False, True):
            original = self.variants[(fast, "original")]
            selected = self.variants[(fast, "ch1234")]
            self.assertEqual(len(original), len(selected))
            differences = {i: (a, b) for i, (a, b) in enumerate(zip(original, selected)) if a != b}
            self.assertEqual(differences, DISPLAY_CHANGES)
            # This complete comparison includes every menu, asset, timer,
            # RF/control instruction, USB helper, and persistence routine.
            self.assertEqual(struct.unpack_from("<I", selected, 0x3BF4)[0], RAM + 0x20C)
            self.assertEqual(struct.unpack_from("<I", selected, 0x3CCC)[0], RAM + 0x210)
            self.assertEqual(selected[0x57C58:0x57C5C], b"CH3\0")
            self.assertEqual(selected[0x57C60:0x57C64], b"CH4\0")

    def test_four_exact_variants_identification_and_revert(self):
        for key, data in self.variants.items():
            with self.subTest(variant=key):
                self.assertEqual(digest(data), EXPECTED[key])
                self.assertEqual(len(data), 627232 if key[0] else 626956)
                self.assertEqual(patcher.inspect_image(data)["dashboard"], key[1])
                self.assertEqual(patcher.revert_patch(data), self.original)
                with self.assertRaises(ValueError):
                    patcher.build_patch(data, dashboard="ch1234")
                altered = bytearray(data)
                altered[0x57C5A] ^= 1
                with self.assertRaises(ValueError):
                    patcher.revert_patch(bytes(altered))

    def test_invalid_api_dashboard_rejected(self):
        for dashboard in ("other", "CH1234", "", None, 123):
            with self.subTest(dashboard=dashboard):
                with self.assertRaises(ValueError):
                    patcher.build_patch(self.original, dashboard=dashboard)

    def test_cli_all_variants_dry_run_roundtrip_and_optimization(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-dashboard-") as name:
            directory = Path(name)
            source = directory / "original.bin"
            source.write_bytes(self.original)
            for optimized in (False, True):
                for key, expected in self.variants.items():
                    fast, dashboard = key
                    with self.subTest(optimized=optimized, variant=key):
                        output = directory / f"patched-{optimized}-{fast}-{dashboard}.bin"
                        restored = directory / f"restored-{optimized}-{fast}-{dashboard}.bin"
                        flags = ["--dashboard", dashboard] + (["--usb-1ms"] if fast else [])
                        dry = cli("patch", source, *flags, "--dry-run", optimized=optimized)
                        self.assertEqual(dry.returncode, 0, dry.stderr)
                        self.assertEqual(json.loads(dry.stdout)["output"]["sha256"], EXPECTED[key])
                        self.assertFalse(output.exists())
                        applied = cli("patch", source, *flags, "--output", output, optimized=optimized)
                        self.assertEqual(applied.returncode, 0, applied.stderr)
                        self.assertEqual(output.read_bytes(), expected)
                        reverted = cli("revert", output, "--output", restored, optimized=optimized)
                        self.assertEqual(reverted.returncode, 0, reverted.stderr)
                        self.assertEqual(restored.read_bytes(), self.original)
            self.assertEqual(source.read_bytes(), self.original)

    @unittest.skipUnless(HAVE_ARM, "optional Unicorn package not installed")
    def test_arm_display_values_bars_and_no_channel_writes(self):
        rng = random.Random(3501234)
        cases = [([v] * 10, 0, 0, force)
                 for v in (-2000, -1667, -1000, -1, 0, 1, 1000, 1667, 2000)
                 for force in (0, 1)]
        cases += [([rng.randint(-2000, 2000) for _ in range(10)],
                   rng.randint(-2000, 2000), rng.randint(-120, 120), rng.randint(0, 1))
                  for _ in range(40)]
        for row in ROWS:
            for index, (channels, cache, last, force) in enumerate(cases):
                oracle_channels = channels.copy()
                oracle_channels[row["old_channel"] - 1] = channels[row["channel"] - 1]
                oracle = self.run_display(self.original, row, oracle_channels, cache, last, force)
                for fast in (False, True):
                    with self.subTest(row=row["channel"], case=index, fast=fast):
                        image = self.variants[(fast, "ch1234")]
                        observed = self.run_display(image, row, channels, cache, last, force)
                        self.assertEqual(observed, oracle)
                        distractors = channels.copy()
                        distractors[4] = -2000 if channels[4] >= 0 else 2000
                        distractors[5] = -2000 if channels[5] >= 0 else 2000
                        self.assertEqual(self.run_display(image, row, distractors, cache, last, force), observed)

    def run_display(self, image, row, channels, cache, last, force):
        machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        machine.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
        machine.mem_map(0x08000000, 0x100000)
        machine.mem_write(BASE, image)
        machine.mem_map(RAM, 0x20000)
        machine.mem_map(STOP, 4096)
        snapshot = struct.pack("<10i", *channels)
        machine.mem_write(RAM + 0x204, snapshot)
        machine.mem_write(row["cache"], struct.pack("<i", cache))
        machine.mem_write(row["last"], struct.pack("<i", last))
        machine.mem_write(row["label"], struct.pack("<I", 0x31000100))
        machine.mem_write(row["bar"], struct.pack("<I", 0x31000200))
        machine.mem_write(STACK - 256, b"\xCC" * 272)
        saved = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                 UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]
        for index, reg in enumerate(saved):
            machine.reg_write(reg, 0x12340000 + index)
        machine.reg_write(UC_ARM_REG_SP, STACK)
        machine.reg_write(UC_ARM_REG_LR, STOP | 1)
        machine.reg_write(UC_ARM_REG_R0, force)
        calls, writes = [], []

        def on_code(cpu, address, size, _):
            if address == BASE + 0x6DC:
                value = signed(cpu.reg_read(UC_ARM_REG_R2))
                output = f"{value:3d}%".encode("ascii") + b"\0"
                cpu.mem_write(cpu.reg_read(UC_ARM_REG_R0), output)
                calls.append(("format", value))
                cpu.reg_write(UC_ARM_REG_R0, len(output) - 1)
            elif address == BASE + 0x4A384:
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R0), 0x31000100)
                buffer = bytes(cpu.mem_read(cpu.reg_read(UC_ARM_REG_R2), 32)).split(b"\0")[0]
                calls.append(("label", buffer.decode("ascii")))
            elif address == BASE + 0x4029E:
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R0), 0x31000200)
                calls.append(("bar", signed(cpu.reg_read(UC_ARM_REG_R1)), cpu.reg_read(UC_ARM_REG_R2)))
            elif BASE + row["start"] <= address < BASE + row["end"]:
                return
            else:
                self.fail(f"Unexpected execution address {address:#x}")
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

        def on_write(cpu, access, address, size, value, _):
            self.assertTrue((STACK - 112 <= address and address + size <= STACK)
                            or (row["cache"] <= address and address + size <= row["last"] + 4))
            writes.append((address, size))

        machine.hook_add(UC_HOOK_CODE, on_code)
        machine.hook_add(UC_HOOK_MEM_WRITE, on_write)
        machine.emu_start((BASE + row["start"]) | 1, STOP, count=500)
        self.assertEqual(machine.reg_read(UC_ARM_REG_PC), STOP)
        self.assertEqual(machine.reg_read(UC_ARM_REG_SP), STACK)
        self.assertEqual(bytes(machine.mem_read(RAM + 0x204, 40)), snapshot)
        self.assertEqual(bytes(machine.mem_read(STACK - 256, 144)), b"\xCC" * 144)
        self.assertEqual(bytes(machine.mem_read(STACK, 16)), b"\xCC" * 16)
        self.assertEqual([machine.reg_read(r) for r in saved], [0x12340000 + i for i in range(len(saved))])
        state = tuple(struct.unpack("<i", machine.mem_read(a, 4))[0] for a in (row["cache"], row["last"]))
        return calls, state, writes


if __name__ == "__main__":
    unittest.main()
