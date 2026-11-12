"""Independent six-row checks using local input, with optional ARM emulation.

The graphics model observes calls and simulates ownership/allocation failure. It
does not execute LVGL, model a real heap/scheduler, render pixels, or prove device
stability. No USB, firmware transfer, or bundled vendor image is involved.
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

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
import patch_firmware as patcher
from test_patch_firmware import cli
from test_dashboard import EXPECTED as PREVIOUS_HASHES

try:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS,
                         UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE)
    from unicorn.arm_const import (
        UC_CPU_ARM_CORTEX_M3, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
        UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
        UC_ARM_REG_R11, UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR,
        UC_ARM_REG_PC,
    )
    HAVE_ARM = True
except ImportError:
    HAVE_ARM = False

BASE, RAM, STACK, STOP = 0x08005000, 0x20000000, 0x2001F000, 0x10000000
PAGE, ROOT, PANEL = 0x200005B4, 0x20000790, 0x200005C4
SOURCE_SHA = "06c47e22049f0ec91823156b3a1afb997dfe31309d06c493aab08426d2866bbc"
SIX_HASHES = {
    False: "f622f91d45b0bc1063cb3c11ff1a82806f2160a91213bfa65db27f34e237f365",
    True: "cb8b9e6f3c3685f874709f93efc7a4b605c4f2384b6f456efbcf7b11570ffdc4",
}
NATIVE_CALLBACK = BASE + 0x59BC8
NATIVE_STATE = BASE + 0x4B6A8
RETURN_VALUE = 0x13572468
APIS = {
    0x49300: "label_create", 0x40014: "bar_create", 0x50244: "size",
    0x501F2: "pos", 0x4B78A: "align", 0x4B7AE: "align_to",
    0x50858: "font", 0x4A384: "text_fmt", 0x4A2F4: "text",
    0x4A2C4: "recolor", 0x4A240: "long_mode", 0x50836: "text_color",
    0x5081C: "text_align", 0x50500: "bg_color", 0x5058A: "bg_opa",
    0x500C4: "style", 0x4B62E: "add_flag", 0x4B6A8: "add_state",
    0x4B6C8: "add_style", 0x401D4: "bar_range", 0x401AC: "bar_mode",
    0x40188: "bar_get_value", 0x4029E: "bar_value", 0x4FBE8: "remove_style_all",
    0x41A98: "color", 0x53CDC: "timer_delete", 0x4C21C: "object_delete",
    0x5047C: "radius", 0x56DD0: "cleanup_group", 0x56DE0: "cleanup_group_mode",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def signed(value):
    return struct.unpack("<i", struct.pack("<I", value & 0xFFFFFFFF))[0]


def percentage(raw):
    raw = max(-2000, min(2000, raw))
    magnitude = (abs(raw) * 3 + 25) // 50
    return -magnitude if raw < 0 else magnitude


@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class SixFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if len(cls.original) != 626956 or sha(cls.original) != SOURCE_SHA:
            raise ValueError("The exact supported official input is required")
        cls.images = {fast: patcher.build_patch(cls.original, usb_1ms=fast, dashboard="ch123456")
                      for fast in (False, True)}
        cls.baselines = {fast: patcher.build_patch(cls.original, usb_1ms=fast, dashboard="original")
                         for fast in (False, True)}

    def test_native_changes_are_only_two_home_hooks(self):
        allowed = set(range(0x59AE4, 0x59AE8)) | set(range(0x5850C, 0x58510))
        for fast, image in self.images.items():
            baseline = self.baselines[fast]
            changes = {i for i in range(len(baseline)) if baseline[i] != image[i]}
            self.assertTrue(changes)
            self.assertTrue(changes <= allowed, f"unexpected modifications {sorted(changes - allowed)}")
            self.assertGreater(len(image), len(baseline))
            # All menu routines, native channel producers, settings routines,
            # graphics assets, cleanup, and the USB helper are covered above.
            self.assertEqual(image[0x57C58:0x57C5C], b"CH5\0")
            self.assertEqual(image[0x57C60:0x57C64], b"CH6\0")

    def test_previous_four_outputs_are_identical_and_all_six_revert(self):
        for (fast, dashboard), expected in PREVIOUS_HASHES.items():
            image = patcher.build_patch(self.original, usb_1ms=fast, dashboard=dashboard)
            self.assertEqual(sha(image), expected)
            self.assertEqual(patcher.revert_patch(image), self.original)
        for fast, image in self.images.items():
            self.assertEqual(sha(image), SIX_HASHES[fast])
            self.assertEqual(len(image), 629568 if fast else 629292)
            self.assertEqual(patcher.inspect_image(image)["dashboard"], "ch123456")
            self.assertEqual(patcher.revert_patch(image), self.original)
            altered = bytearray(image)
            altered[-1] ^= 1
            with self.assertRaises(ValueError):
                patcher.revert_patch(bytes(altered))

    def test_cli_six_rows_roundtrip_and_dry_run(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-six-") as name:
            directory = Path(name)
            source = directory / "original.bin"
            source.write_bytes(self.original)
            for optimized in (False, True):
                for fast, expected in self.images.items():
                    flags = ["--dashboard", "ch123456"] + (["--usb-1ms"] if fast else [])
                    output = directory / f"six-{optimized}-{fast}.bin"
                    restored = directory / f"restored-{optimized}-{fast}.bin"
                    dry = cli("patch", source, *flags, "--dry-run", "--output", output,
                              optimized=optimized)
                    self.assertEqual(dry.returncode, 0, dry.stderr)
                    self.assertEqual(json.loads(dry.stdout)["output"]["sha256"], sha(expected))
                    self.assertFalse(output.exists())
                    result = cli("patch", source, *flags, "--output", output, optimized=optimized)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_bytes(), expected)
                    result = cli("revert", output, "--output", restored, optimized=optimized)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(restored.read_bytes(), self.original)


class GraphicsProbe:
    """Synthetic object tree with strict access checks; no real LVGL execution."""
    def __init__(self, test, image, baseline_size):
        self.test, self.image, self.new_start = test, image, BASE + baseline_size
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
        self.cpu.mem_map(0x08000000, 0x100000)
        self.cpu.mem_write(BASE, image)
        self.cpu.mem_map(RAM, 0x20000)
        self.cpu.mem_map(STOP, 4096)
        self.objects, self.calls, self.reads = {}, [], []
        self.api_names = APIS
        self.next_index = 0
        self.creations, self.fail_at = 0, None
        self.native_callback_action = None
        self.saved = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                      UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]
        self.argument_regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        self.allowed_native = []
        self.min_sp = STACK
        self.prepare_home()
        self.cpu.hook_add(UC_HOOK_CODE, self.on_code)
        self.cpu.hook_add(UC_HOOK_MEM_READ, self.on_read)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self.on_write)

    def word(self, address):
        return struct.unpack("<I", self.cpu.mem_read(address, 4))[0]

    def put(self, address, value):
        self.cpu.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def text(self, address):
        data = bytes(self.cpu.mem_read(address, 256)).split(b"\0")[0]
        return data.decode("ascii")

    def allocate(self, kind, parent):
        index = self.next_index
        self.next_index += 1
        address = RAM + 0x10000 + index * 0x80
        spec = RAM + 0x8000 + index * 0x20
        children = RAM + 0xA000 + index * 0x100
        self.test.assertLess(children + 0x100, RAM + 0x10000)
        class_pointer = BASE + {"obj": 0xF1000, "label": 0xF1100, "bar": 0xF1200}[kind]
        self.put(address, class_pointer)
        self.put(address + 4, parent)
        self.put(address + 8, spec)
        self.put(spec, children)
        self.put(spec + 4, 0)
        self.objects[address] = {"kind": kind, "parent": parent, "children": [], "alive": True,
                                 "text": "", "value": 0, "size": None, "align": None}
        if parent:
            self.objects[parent]["children"].append(address)
            self.sync_children(parent)
        return address

    def sync_children(self, parent):
        items = self.objects[parent]["children"]
        spec = self.word(parent + 8)
        self.put(spec + 4, len(items))
        for index, child in enumerate(items):
            self.put(self.word(spec) + index * 4, child)

    def prepare_home(self):
        root = self.allocate("obj", 0)
        self.put(ROOT, root)
        self.cpu.mem_write(PAGE, b"\1")
        self.put(PANEL, self.allocate("obj", root))
        self.put(0x200005D8, self.allocate("label", root))
        for pointer in (0x20000664, 0x20000668, 0x2000066C, 0x20000670,
                        0x20000674, 0x20000678, 0x2000067C, 0x20000680):
            self.put(pointer, self.allocate("label", root))
        for pointer in (0x20000684, 0x20000688, 0x2000068C, 0x20000690):
            self.put(pointer, self.allocate("bar", root))
        self.cpu.mem_write(RAM + 0x204, struct.pack("<10i", *([0] * 10)))
        return root

    def delete_tree(self, address):
        self.test.assertTrue(self.objects[address]["alive"])
        for child in list(self.objects[address]["children"]):
            self.delete_tree(child)
        self.objects[address]["alive"] = False
        parent = self.objects[address]["parent"]
        if parent and address in self.objects[parent]["children"]:
            self.objects[parent]["children"].remove(address)
            self.sync_children(parent)

    def return_api(self, value):
        lr = self.cpu.reg_read(UC_ARM_REG_LR)
        for reg, result in zip(self.argument_regs, (value, 0x15551555, 0x26662666, 0x37773777)):
            self.cpu.reg_write(reg, result & 0xFFFFFFFF)
        self.cpu.reg_write(UC_ARM_REG_R12, 0xCCCC5555)
        self.cpu.reg_write(UC_ARM_REG_PC, lr)

    def on_code(self, cpu, address, size, _):
        self.min_sp = min(self.min_sp, cpu.reg_read(UC_ARM_REG_SP))
        if self.new_start <= address < BASE + len(self.image):
            return
        if any(start <= address < end for start, end in self.allowed_native):
            return
        self.test.assertEqual(cpu.reg_read(UC_ARM_REG_SP) % 8, 0, f"unaligned call {address:#x}")
        args = [cpu.reg_read(reg) for reg in self.argument_regs]
        name = "native_callback" if address == NATIVE_CALLBACK else self.api_names.get(address - BASE)
        self.test.assertIsNotNone(name, f"unexpected execution at {address:#x}")
        self.calls.append((name, tuple(args)))
        result = RETURN_VALUE
        if name == "native_callback":
            if self.native_callback_action:
                self.native_callback_action(self)
        elif name in ("timer_delete", "cleanup_group", "cleanup_group_mode"):
            pass
        elif name == "color":
            r, g, b = args[:3]
            value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            result = ((value & 255) << 8) | (value >> 8)
        else:
            self.test.assertIn(args[0], self.objects, f"unknown object for {name}: {args[0]:#x}")
            obj = self.objects[args[0]]
            self.test.assertTrue(obj["alive"], f"use after cleanup in {name}")
            if name.endswith("_create"):
                self.creations += 1
                if self.creations == self.fail_at:
                    result = 0
                else:
                    result = self.allocate(name.split("_")[0], args[0])
            elif name == "object_delete":
                self.delete_tree(args[0])
            elif name == "text":
                self.test.assertEqual(obj["kind"], "label")
                obj["text"] = self.text(args[1])
            elif name == "text_fmt":
                self.test.assertEqual(obj["kind"], "label")
                self.test.assertIn(self.text(args[1]), ("%d%%", "%3d%%"))
                obj["text"] = str(signed(args[2])) + "%"
            elif name in ("bar_value", "bar_get_value", "bar_range", "bar_mode"):
                self.test.assertEqual(obj["kind"], "bar")
                if name == "bar_get_value":
                    result = obj["value"]
                elif name == "bar_value":
                    self.test.assertEqual(args[2], 0, "unexpected animation")
                    obj["value"] = signed(args[1])
                elif name == "bar_range":
                    obj["range"] = (signed(args[1]), signed(args[2]))
            elif name == "size":
                obj["size"] = (signed(args[1]), signed(args[2]))
            elif name == "align":
                obj["align"] = (args[1], signed(args[2]), signed(args[3]))
            elif name == "pos":
                obj["pos"] = (signed(args[1]), signed(args[2]))
        self.return_api(result)

    def on_read(self, cpu, access, address, size, value, _):
        self.reads.append((address, size))

    def on_write(self, cpu, access, address, size, value, _):
        permitted = STACK - 512 <= address and address + size <= STACK
        if self.allowed_native:
            permitted = permitted or address in (ROOT, 0x200005B8, 0x200005BC, 0x200005C0, 0x200005B5)
        self.test.assertTrue(permitted, f"unexpected CPU write outside stack at {address:#x}")

    def run(self, entry, args=(), expected_return=None):
        self.calls, self.reads, self.min_sp = [], [], STACK
        self.cpu.mem_write(STACK - 768, b"\xCC" * 800)
        self.cpu.reg_write(UC_ARM_REG_SP, STACK)
        self.cpu.reg_write(UC_ARM_REG_LR, STOP | 1)
        for i, reg in enumerate(self.saved):
            self.cpu.reg_write(reg, 0xA0010000 + i * 0x111)
        for reg, value in zip(self.argument_regs, args):
            self.cpu.reg_write(reg, value & 0xFFFFFFFF)
        commands = bytes(self.cpu.mem_read(RAM + 0x204, 40))
        self.cpu.emu_start(entry | 1, STOP, count=20000)
        self.test.assertEqual(self.cpu.reg_read(UC_ARM_REG_PC), STOP)
        self.test.assertEqual(self.cpu.reg_read(UC_ARM_REG_SP), STACK)
        self.test.assertEqual([self.cpu.reg_read(r) for r in self.saved],
                              [0xA0010000 + i * 0x111 for i in range(len(self.saved))])
        self.test.assertEqual(bytes(self.cpu.mem_read(RAM + 0x204, 40)), commands)
        self.test.assertEqual(bytes(self.cpu.mem_read(STACK - 768, 256)), b"\xCC" * 256)
        self.test.assertEqual(bytes(self.cpu.mem_read(STACK, 32)), b"\xCC" * 32)
        if expected_return is not None:
            self.test.assertEqual(self.cpu.reg_read(UC_ARM_REG_R0), expected_return)
        return self.calls


@unittest.skipUnless(HAVE_ARM, "optional capstone/unicorn packages not installed")
@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class SixArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if sha(original) != SOURCE_SHA:
            raise ValueError("The exact supported official input is required")
        cls.images = {fast: patcher.build_patch(original, usb_1ms=fast, dashboard="ch123456")
                      for fast in (False, True)}
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        decoder.detail = True
        cls.entries = {}
        for fast, image in cls.images.items():
            hook = list(decoder.disasm(image[0x59AE4:0x59AE8], BASE + 0x59AE4))
            if len(hook) != 1 or hook[0].mnemonic != "bl":
                raise ValueError("Expected a single constructor BL hook")
            cls.entries[fast] = (hook[0].operands[0].imm, struct.unpack_from("<I", image, 0x5850C)[0] & ~1)

    def probe(self, fast=False, construct=True):
        probe = GraphicsProbe(self, self.images[fast], 627232 if fast else 626956)
        if construct:
            probe.run(self.entries[fast][0], (probe.word(0x200005D8), 2), RETURN_VALUE)
        return probe

    def test_constructor_six_owned_children_and_native_layout(self):
        for fast in (False, True):
            probe = self.probe(fast)
            panel = probe.word(PANEL)
            children = probe.objects[panel]["children"]
            self.assertEqual(len(children), 6)
            self.assertEqual([probe.objects[p]["kind"] for p in children],
                             ["label", "label", "bar", "label", "label", "bar"])
            self.assertEqual([probe.objects[p]["text"] for p in (children[0], children[3])], ["CH3", "CH4"])
            self.assertTrue(all(probe.objects[p]["parent"] == panel for p in children))
            for p in (children[2], children[5]):
                self.assertEqual(probe.objects[p]["size"], (120, 8))
                self.assertEqual(probe.objects[p]["range"], (-120, 120))
            for i, y in ((0, 34), (3, 50)):
                self.assertEqual(probe.objects[children[i]]["size"], (25, 16))
                self.assertEqual(probe.objects[children[i + 1]]["size"], (40, 16))
                self.assertEqual(probe.objects[children[i]]["align"], (1, 5, y))
                self.assertEqual(probe.objects[children[i + 1]]["align"], (1, 160, y))
                self.assertEqual(probe.objects[children[i + 2]]["align"], (1, 35, y + 3))
            for title, value, bar, y in ((0x20000664, 0x20000668, 0x20000684, 202),
                                          (0x2000066C, 0x20000670, 0x20000688, 218),
                                          (0x20000674, 0x20000678, 0x2000068C, 266),
                                          (0x2000067C, 0x20000680, 0x20000690, 282)):
                self.assertEqual(probe.objects[probe.word(title)]["align"], (1, 25, y))
                self.assertEqual(probe.objects[probe.word(value)]["align"], (1, 180, y))
                self.assertEqual(probe.objects[probe.word(bar)]["align"], (1, 55, y + 3))
                self.assertEqual(probe.objects[probe.word(title)]["size"], (25, 16))
                self.assertLessEqual(y + 16, 300)
            self.assertFalse(any(name in ("timer_delete", "object_delete") for name, _ in probe.calls))
            self.assertEqual(probe.calls[0][0], "add_state")
            previous_creations = probe.creations
            probe.run(self.entries[fast][0], (probe.word(0x200005D8), 2), RETURN_VALUE)
            self.assertEqual(probe.creations, previous_creations, "repeat call must not leak more children")

    def test_direct_percentage_readings_and_change_only_updates(self):
        rng = random.Random(3506)
        values = [-100000, -2001, -2000, -1667, -25, -9, -8, -1, 0, 1, 8, 9, 25,
                  1667, 2000, 2001, 100000] + [rng.randrange(-3000, 3001) for _ in range(30)]
        for fast in (False, True):
            probe = self.probe(fast)
            children = probe.objects[probe.word(PANEL)]["children"]
            for value in values:
                probe.put(RAM + 0x20C, value)
                probe.put(RAM + 0x210, -value)
                calls = probe.run(self.entries[fast][1], (0x20007800,))
                self.assertEqual(calls[0][0], "native_callback")
                self.assertEqual(calls[0][1][0], 0x20007800)
                self.assertEqual(probe.objects[children[1]]["text"], f"{percentage(value)}%")
                self.assertEqual(probe.objects[children[2]]["value"], percentage(value))
                self.assertEqual(probe.objects[children[4]]["text"], f"{percentage(-value)}%")
                self.assertEqual(probe.objects[children[5]]["value"], percentage(-value))
                repeated = probe.run(self.entries[fast][1], (0x20007800,))
                self.assertFalse(any(name in ("text", "text_fmt", "bar_value") for name, _ in repeated))

    def test_page_and_root_guards_before_native_callback(self):
        for fast in (False, True):
            for missing_root, page in ((True, 1), (False, 2), (False, 0)):
                probe = self.probe(fast)
                if missing_root:
                    probe.put(ROOT, 0)
                probe.cpu.mem_write(PAGE, bytes([page]))
                calls = probe.run(self.entries[fast][1], (0x20007800,))
                self.assertEqual(calls, [])
                probe = self.probe(fast, construct=False)
                if missing_root:
                    probe.put(ROOT, 0)
                probe.cpu.mem_write(PAGE, bytes([page]))
                calls = probe.run(self.entries[fast][0], (probe.word(0x200005D8), 2), RETURN_VALUE)
                self.assertEqual([name for name, _ in calls], ["add_state"])
                self.assertEqual(probe.creations, 0)

    def test_incomplete_container_and_native_anchor_guards(self):
        for fast in (False, True):
            for fault in ("panel", "spec", "array", "count0", "count5", "count7", "label_anchor", "bar_anchor"):
                probe = self.probe(fast)
                panel = probe.word(PANEL)
                spec = probe.word(panel + 8)
                if fault == "panel":
                    probe.put(PANEL, 0)
                elif fault == "spec":
                    probe.put(panel + 8, 0)
                elif fault == "array":
                    probe.put(spec, 0)
                elif fault.startswith("count"):
                    probe.put(spec + 4, int(fault[-1]))
                else:
                    probe.put(0x20000664 if fault == "label_anchor" else 0x20000684, 0)
                calls = probe.run(self.entries[fast][1], (0x20007800,))
                self.assertEqual([name for name, _ in calls], ["native_callback"])

    def test_native_callback_can_close_home_without_late_widget_access(self):
        for fast in (False, True):
            probe = self.probe(fast)
            def close_home(scene):
                scene.delete_tree(scene.word(ROOT))
                scene.put(ROOT, 0)
            probe.native_callback_action = close_home
            calls = probe.run(self.entries[fast][1], (0x20007800,))
            self.assertEqual([name for name, _ in calls], ["native_callback"])

    def test_partial_allocation_and_bad_child_guards(self):
        for fast in (False, True):
            for failed in range(1, 7):
                probe = self.probe(fast, construct=False)
                probe.fail_at = failed
                probe.run(self.entries[fast][0], (probe.word(0x200005D8), 2), RETURN_VALUE)
                self.assertEqual(probe.objects[probe.word(PANEL)]["children"], [])
                for slot in range(0x20000664, 0x20000694, 4):
                    self.assertIsNone(probe.objects[probe.word(slot)]["align"])
                calls = probe.run(self.entries[fast][1], (0x20007800,))
                self.assertEqual([name for name, _ in calls], ["native_callback"])
            for field in ("null", "wrong_parent", "wrong_class"):
                for index in range(6):
                    probe = self.probe(fast)
                    panel = probe.word(PANEL)
                    children = probe.objects[panel]["children"]
                    child = children[index]
                    if field == "null":
                        probe.put(probe.word(probe.word(panel + 8)) + index * 4, 0)
                    elif field == "wrong_parent":
                        probe.put(child + 4, probe.word(ROOT))
                    else:
                        probe.put(child, 0x080FF000)
                    calls = probe.run(self.entries[fast][1], (0x20007800,))
                    self.assertEqual([name for name, _ in calls], ["native_callback"])

    def test_native_cleanup_deletes_owned_children_and_reopen_is_fresh(self):
        for fast in (False, True):
            probe = self.probe(fast)
            old_root = probe.word(ROOT)
            old_children = probe.objects[probe.word(PANEL)]["children"].copy()
            for slot, value in ((0x200005B8, 0x20007700), (0x200005BC, 0x20007720), (0x200005C0, 0x20007740)):
                probe.put(slot, value)
            probe.allowed_native = [(BASE + 0x59B50, BASE + 0x59BB4)]
            probe.run(BASE + 0x59B50)
            self.assertEqual(probe.word(ROOT), 0)
            self.assertFalse(probe.objects[old_root]["alive"])
            self.assertTrue(all(not probe.objects[p]["alive"] for p in old_children))
            relevant = [name for name, _ in probe.calls if name in ("timer_delete", "object_delete")]
            self.assertEqual(relevant, ["timer_delete"] * 3 + ["object_delete"])
            probe.allowed_native = []
            self.assertEqual(probe.run(self.entries[fast][1], (0x20007800,)), [])
            probe.prepare_home()
            probe.run(self.entries[fast][0], (probe.word(0x200005D8), 2), RETURN_VALUE)
            new_children = probe.objects[probe.word(PANEL)]["children"]
            self.assertEqual(len(new_children), 6)
            self.assertTrue(set(new_children).isdisjoint(old_children))
            probe.put(RAM + 0x20C, 1667)
            probe.put(RAM + 0x210, -1667)
            probe.run(self.entries[fast][1], (0x20007800,))
            self.assertEqual(probe.objects[new_children[2]]["value"], 100)
            self.assertEqual(probe.objects[new_children[5]]["value"], -100)

    def test_native_font_bounds_for_six_titles_and_full_numeric_range(self):
        image = self.images[False]
        font = 0x0806E750
        callback = struct.unpack_from("<I", image, font - BASE)[0]
        line_height = struct.unpack_from("<h", image, font - BASE + 8)[0]
        self.assertLessEqual(line_height, 16)
        glyphs = {}
        for char in "CH0123456789-% ":
            machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
            machine.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
            machine.mem_map(0x08000000, 0x100000)
            machine.mem_write(BASE, image)
            machine.mem_map(RAM, 0x20000)
            machine.mem_map(STOP, 4096)
            for reg, value in ((UC_ARM_REG_R0, font), (UC_ARM_REG_R1, RAM + 0x4000),
                               (UC_ARM_REG_R2, ord(char)), (UC_ARM_REG_R3, 0),
                               (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, STOP | 1)):
                machine.reg_write(reg, value)
            machine.emu_start(callback | 1, STOP, count=20000)
            self.assertEqual(machine.reg_read(UC_ARM_REG_PC), STOP)
            self.assertNotEqual(machine.reg_read(UC_ARM_REG_R0), 0)
            advance, width, height, x_offset, y_offset = struct.unpack_from(
                "<HHHhh", bytes(machine.mem_read(RAM + 0x4000, 16)), 4)
            self.assertLessEqual(height, line_height)
            glyphs[char] = (advance, width, x_offset)
        def width_of(text):
            advance, edge = 0, 0
            for char in text:
                step, pixels, offset = glyphs[char]
                edge = max(edge, advance + offset + pixels)
                advance += step
            return max(advance, edge)
        self.assertLessEqual(max(width_of(f"CH{i}") for i in range(1, 7)), 25)
        self.assertLessEqual(max(width_of(f"{value}%") for value in range(-120, 121)), 40)


if __name__ == "__main__":
    unittest.main()
