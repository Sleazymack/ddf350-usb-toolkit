"""Independent bounded validation of user layouts and generated ARM hooks.

No device access. Graphics calls use an ownership/allocation model, not LVGL's
allocator or renderer. Separate native tests execute clipping, group selection
and arc value-to-angle code, with drawing notifications observed or suppressed.
These checks do not establish LCD appearance or long-term hardware stability.
"""
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard_custom as custom
import patch_firmware as patcher
from test_patch_firmware import cli
from test_dashboard_six import (
    APIS, BASE, RAM, STACK, STOP, PAGE, ROOT, PANEL, SOURCE_SHA, RETURN_VALUE,
    NATIVE_CALLBACK, HAVE_ARM, GraphicsProbe, percentage, signed, SIX_HASHES,
)

if HAVE_ARM:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
    from unicorn.arm_const import (
        UC_CPU_ARM_CORTEX_M3, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R12, UC_ARM_REG_SP,
        UC_ARM_REG_LR, UC_ARM_REG_PC,
    )


def widget(channel=1, kind="bar", col=0, row=0, color="#55b8f0"):
    return dict(id=f"g{channel}", channel=channel, kind=kind, col=col, row=row, color=color)


def layout(items=None):
    return dict(schema=1, background="#162d46", widgets=items if items is not None else [widget()])


FULL = layout([widget(i + 1, row=i) for i in range(4)]
              + [widget(5, "semicircle", 4, 0), widget(6, "semicircle", 4, 2)])
SEMIS = layout([widget(i + 1, "semicircle", (i % 3) * 2, (i // 3) * 2) for i in range(6)])


def cells(item):
    width, height = (4, 1) if item["kind"] == "bar" else (2, 2)
    return {(x, y) for y in range(item["row"], item["row"] + height)
            for x in range(item["col"], item["col"] + width)}


def color16(value):
    rgb = int(value[1:], 16)
    word = (((rgb >> 16) & 255) // 8) * 2048 + (((rgb >> 8) & 255) // 4) * 32 + (rgb & 255) // 8
    return (word % 256) * 256 + word // 256


class LayoutValidationTests(unittest.TestCase):
    def test_all_single_positions_and_pair_collisions(self):
        valid = []
        for kind, col, row in itertools.product(("bar", "semicircle"), range(-1, 7), range(-1, 5)):
            item = widget(kind=kind, col=col, row=row)
            fits = all(0 <= x < 6 and 0 <= y < 4 for x, y in cells(item))
            if fits:
                normalized = custom.validate_layout(layout([item]))
                valid.append(item)
                x, y, width, height = custom.rectangle(normalized["widgets"][0])
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertGreaterEqual(min(x, y), 0)
                self.assertLessEqual(x + width, 215)
                self.assertLessEqual(y + height, 100)
            else:
                with self.assertRaises(ValueError):
                    custom.validate_layout(layout([item]))
        for first, second in itertools.product(valid, repeat=2):
            second = dict(second, id="other", channel=2)
            if cells(first) & cells(second):
                with self.assertRaises(ValueError):
                    custom.validate_layout(layout([first, second]))
            else:
                result = custom.validate_layout(layout([first, second]))
                a, b = map(custom.rectangle, result["widgets"])
                self.assertTrue(a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                                or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])

    def test_strict_types_unknown_fields_and_injection_are_rejected(self):
        for field in ("schema", "background", "widgets"):
            wrong = layout()
            del wrong[field]
            with self.assertRaises(ValueError):
                custom.validate_layout(wrong)
        invalid = [None, [], {}, dict(layout(), code="import os"), dict(layout(), schema=True),
                   dict(layout(), widgets=[]), dict(layout(), widgets=[widget()] * 7)]
        for field in ("channel", "col", "row"):
            for value in (True, False, None, 1.0, "1", float("nan"), float("inf"), -999, 2**64):
                item = widget()
                item[field] = value
                invalid.append(layout([item]))
        for field, values in {
            "id": ("", "x" * 25, "a/b", "é", "__import__('os')", "bad\0id"),
            "kind": ("arc", "eval", "BAR", 0, None),
            "color": ("red", "#123", "#12345678", "#gg0000", 0, "#000000;cmd"),
        }.items():
            for value in values:
                item = widget()
                item[field] = value
                invalid.append(layout([item]))
        invalid += [layout([dict(widget(), extra=1)]), layout([widget(), widget(1, row=1)]),
                    layout([widget(), dict(widget(2, row=1), id="g1")])]
        for candidate in invalid:
            with self.subTest(candidate=repr(candidate)[:120]):
                with self.assertRaises(ValueError):
                    custom.validate_layout(candidate)

    def test_json_parser_rejects_duplicate_fields_trailing_code_and_oversize(self):
        good = json.dumps(layout())
        invalid = [good + "__import__('os')", good.replace('"schema": 1', '"schema": 1, "schema": 1'),
                   good.replace('"col": 0', '"col": NaN'), "[" * 1500 + "]" * 1500,
                   " " * 4097, b"\xff\xfe", good.replace('"channel": 1', '"channel": true')]
        for data in invalid:
            with self.assertRaises(ValueError):
                custom.parse_layout(data)
        self.assertEqual(custom.parse_layout(good), custom.validate_layout(layout()))

    def test_canonicalization_is_deterministic_without_mutating_input(self):
        original = copy.deepcopy(FULL)
        canonical = custom.canonical_json(original)
        for seed in range(12):
            changed = copy.deepcopy(original)
            random.Random(seed).shuffle(changed["widgets"])
            changed["background"] = changed["background"].upper()
            for item in changed["widgets"]:
                item["color"] = item["color"].upper()
            self.assertEqual(custom.canonical_json(changed), canonical)
        self.assertEqual(original, FULL)
        normalized = custom.validate_layout(original)
        normalized["widgets"][0]["channel"] = 99
        self.assertEqual(original, FULL)


@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class CustomImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if hashlib.sha256(cls.original).hexdigest() != SOURCE_SHA:
            raise ValueError("Exact supported firmware required")

    def test_deterministic_build_full_byte_scope_and_exact_revert(self):
        layouts = [layout(), layout([widget(1, "semicircle", 4, 2)]), FULL, SEMIS]
        for fast, spec in itertools.product((False, True), layouts):
            with self.subTest(fast=fast, widgets=len(spec["widgets"])):
                result = patcher.build_patch(self.original, usb_1ms=fast, dashboard="custom", layout=spec)
                baseline = patcher.build_patch(self.original, usb_1ms=fast)
                allowed = set(range(0x59AE4, 0x59AE8)) | set(range(0x5850C, 0x58510))
                changed = {i for i in range(len(baseline)) if result[i] != baseline[i]}
                self.assertTrue(changed <= allowed)
                self.assertEqual(len(result) % 4, 0)
                self.assertLess(BASE + len(result), 0x080F5000)
                self.assertLessEqual(len(result), 660000)
                self.assertEqual(result, patcher.build_patch(self.original, usb_1ms=fast,
                                                            dashboard="custom", layout=copy.deepcopy(spec)))
                info = patcher.inspect_image(result)
                self.assertTrue(info["recognized"])
                self.assertTrue(info["custom_verified_by_complete_regeneration"])
                self.assertEqual(info["layout"], custom.validate_layout(spec))
                self.assertEqual(patcher.revert_patch(result), self.original)
        for fast, expected in SIX_HASHES.items():
            self.assertEqual(hashlib.sha256(patcher.build_patch(self.original, usb_1ms=fast,
                                                               dashboard="ch123456")).hexdigest(), expected)

    def test_metadata_does_not_authenticate_modified_code_or_stock(self):
        for fast in (False, True):
            result = patcher.build_patch(self.original, usb_1ms=fast, dashboard="custom", layout=FULL)
            samples = {0, 0x21B0E, 0x2C8A2, 0x57C5A, 0x5850C, 0x59AE4, 626956,
                       len(result) - 1, len(result) - 20, len(result) - 80}
            samples.update(random.Random(3504).sample(range(len(result)), 12))
            bad = []
            for position in samples:
                mutated = bytearray(result)
                mutated[position] ^= 1
                bad.append(bytes(mutated))
            bad.extend((result[:-1], result + b"\0", result + b"evil", result[:-20] + b"\xff" * 20))
            # A valid alternate trailer attached to old code must also fail.
            other = copy.deepcopy(FULL)
            other["background"] = "#123456"
            trailer_size = len(custom.make_trailer(FULL, fast))
            bad.append(result[:-trailer_size] + custom.make_trailer(other, fast))
            bad.append(result[:-trailer_size] + custom.make_trailer(FULL, not fast))
            for candidate in bad:
                self.assertFalse(patcher.inspect_image(candidate)["recognized"])
                with self.assertRaises(ValueError):
                    patcher.revert_patch(candidate)

    def test_cli_layout_file_and_python_optimization(self):
        with tempfile.TemporaryDirectory(prefix="ddf350-custom-") as name:
            directory = Path(name)
            source, spec = directory / "source.bin", directory / "layout.json"
            source.write_bytes(self.original)
            spec.write_text(json.dumps(FULL), encoding="utf-8")
            for optimized in (False, True):
                output = directory / f"custom-{optimized}.bin"
                result = cli("patch", source, "--dashboard", "custom", "--layout", spec,
                             "--usb-1ms", "--output", output, "--dry-run", optimized=optimized)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(output.exists())
                result = cli("patch", source, "--dashboard", "custom", "--layout", spec,
                             "--usb-1ms", "--output", output, optimized=optimized)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(patcher.revert_patch(output.read_bytes()), self.original)


class CustomProbe(GraphicsProbe):
    def __init__(self, test, image, baseline_size):
        super().__init__(test, image, baseline_size)
        self.api_names = dict(APIS, **{})
        self.api_names.update({0x4C1FC: "obj_create", 0x3F1B4: "arc_create",
                               0x3F8A8: "arc_get_value", 0x3FB60: "arc_value",
                               0x3FA78: "arc_range", 0x3F8CE: "arc_bg_angles",
                               0x3FABE: "arc_rotation", 0x4FA96: "remove_style",
                               0x4C070: "clear_flag"})

    def allocate(self, kind, parent):
        address = super().allocate("bar" if kind == "arc" else kind, parent)
        obj = self.objects[address]
        obj.update(kind=kind, flags=0x80012, styles={}, colors={}, removed_parts=[])
        if kind == "arc":
            self.put(address, BASE + 0xF1300)
        self.put(address + 0x1C, obj["flags"])
        return address

    def prepare_home(self):
        root = super().prepare_home()
        self.put(0x200005CC, self.allocate("arc", root))
        return root

    def on_write(self,cpu,access,address,size,value,unused):
        arc=self.objects.get(address-0x34)
        if (size==2 and arc and arc['kind']=='arc' and arc['alive']
                and self.objects[arc['parent']]['parent']==self.word(PANEL)):
            old=int.from_bytes(cpu.mem_read(address,2),'little')
            self.test.assertEqual(value,(old & ~6) | 2)
            self.test.assertFalse(arc.get('centered_mode'))
            arc['centered_mode']=True
            return
        super().on_write(cpu,access,address,size,value,unused)

    def on_code(self, cpu, address, size, unused):
        name = self.api_names.get(address - BASE)
        custom_calls = {"arc_get_value", "arc_value", "arc_range", "arc_bg_angles", "arc_rotation",
                        "clear_flag", "add_flag", "remove_style", "style", "text_color", "bg_color"}
        if name not in custom_calls:
            return super().on_code(cpu, address, size, unused)
        self.min_sp = min(self.min_sp, cpu.reg_read(UC_ARM_REG_SP))
        self.test.assertEqual(cpu.reg_read(UC_ARM_REG_SP) % 8, 0)
        args = [cpu.reg_read(r) for r in self.argument_regs]
        self.calls.append((name, tuple(args)))
        self.test.assertIn(args[0], self.objects)
        obj = self.objects[args[0]]
        self.test.assertTrue(obj["alive"], "use after cleanup")
        result = RETURN_VALUE
        if name.startswith("arc_"):
            self.test.assertEqual(obj["kind"], "arc")
            if name == "arc_get_value":
                result = obj["value"]
            elif name == "arc_value":
                obj["value"] = signed(args[1])
            elif name == "arc_range":
                obj["range"] = (signed(args[1]), signed(args[2]))
            elif name == "arc_bg_angles":
                obj["angles"] = (args[1], args[2])
        elif name in ("clear_flag", "add_flag"):
            obj["flags"] = obj["flags"] & ~args[1] if name == "clear_flag" else obj["flags"] | args[1]
            self.put(args[0] + 0x1C, obj["flags"])
        elif name == "style":
            obj["styles"][(args[1], args[3])] = args[2]
        elif name == "remove_style":
            obj["removed_parts"].append(args[2])
        else:
            obj["colors"][(name, args[2])] = args[1]
        self.return_api(result)


@unittest.skipUnless(HAVE_ARM, "optional capstone/unicorn packages not installed")
@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class CustomArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if hashlib.sha256(cls.original).hexdigest() != SOURCE_SHA:
            raise ValueError("Exact supported firmware required")

    def probe(self, spec=FULL, fast=False, construct=True):
        image = patcher.build_patch(self.original, usb_1ms=fast, dashboard="custom", layout=spec)
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        decoder.detail = True
        constructor = next(decoder.disasm(image[0x59AE4:0x59AE8], BASE + 0x59AE4)).operands[0].imm
        timer = struct.unpack_from("<I", image, 0x5850C)[0] & ~1
        scene = CustomProbe(self, image, 627232 if fast else 626956)
        scene.constructor, scene.timer = constructor, timer
        if construct:
            scene.run(constructor, (scene.word(0x200005D8), 2), RETURN_VALUE)
        return scene

    def test_complete_typed_tree_geometry_colors_and_clipped_flags(self):
        for fast, spec in itertools.product((False, True), (FULL, SEMIS)):
            probe = self.probe(spec, fast)
            panel = probe.word(PANEL)
            containers = probe.objects[panel]["children"]
            widgets = custom.validate_layout(spec)["widgets"]
            self.assertEqual(probe.creations, len(widgets) * 4)
            self.assertEqual(len(containers), len(widgets))
            for container, item in zip(containers, widgets):
                obj = probe.objects[container]
                x, y, width, height = custom.rectangle(item)
                self.assertEqual(obj["size"], (width, height))
                self.assertEqual(obj["align"], (1, x, y))
                self.assertEqual(obj["flags"] & 0x80013, 0)
                self.assertEqual(len(obj["children"]), 3)
                gauge, title, value = (probe.objects[p] for p in obj["children"])
                parts = custom.widget_parts(item)
                self.assertEqual(parts["container"], (x, y, width, height))
                for part, observed in (("gauge", gauge), ("title", title), ("value", value)):
                    _, px, py = observed["align"]
                    self.assertEqual(parts[part], (px, py, *observed["size"]))
                self.assertEqual([gauge["kind"], title["kind"], value["kind"]],
                                 ["bar" if item["kind"] == "bar" else "arc", "label", "label"])
                self.assertEqual(title["text"], f"CH{item['channel']}")
                self.assertEqual(gauge["range"], (-120, 120))
                self.assertEqual(gauge["flags"] & 0x80012, 0)
                for label in (title, value):
                    self.assertEqual(label["colors"][("text_color", 0)], color16(item["color"]))
                    _, lx, ly = label["align"]
                    lw, lh = label["size"]
                    self.assertGreaterEqual(min(lx, ly), 0)
                    self.assertLessEqual(lx + lw, width)
                    self.assertLessEqual(ly + lh, height)
                if item["kind"] == "semicircle":
                    self.assertEqual(gauge["angles"], (180, 360))
                    self.assertIn(0x30000, gauge["removed_parts"])
                    self.assertEqual(gauge["styles"][(0x52, 0x20000)], color16(item["color"]))
                else:
                    _, gx, gy = gauge["align"]
                    self.assertLessEqual(gx + gauge["size"][0], width)
                    self.assertLessEqual(gy + gauge["size"][1], height)
            for slot in range(0x20000664, 0x20000694, 4):
                self.assertEqual(probe.objects[probe.word(slot)]["flags"] & 1, 1)
            before = probe.creations
            probe.run(probe.constructor, (probe.word(0x200005D8), 2), RETURN_VALUE)
            self.assertEqual(probe.creations, before)

    def test_all_six_values_abi_guards_and_change_only_updates(self):
        for fast, spec in itertools.product((False, True), (FULL, SEMIS)):
            probe = self.probe(spec, fast)
            widgets = custom.validate_layout(spec)["widgets"]
            containers = probe.objects[probe.word(PANEL)]["children"]
            for iteration in range(12):
                values = [(-1 if i % 2 else 1) * (iteration * 217 + i * 77) for i in range(6)]
                probe.cpu.mem_write(RAM + 0x204, struct.pack("<6i", *values))
                calls = probe.run(probe.timer, (0x20007800,))
                self.assertEqual(calls[0][0], "native_callback")
                for container, item in zip(containers, widgets):
                    gauge, _, value = probe.objects[container]["children"]
                    expected = percentage(values[item["channel"] - 1])
                    self.assertEqual(probe.objects[gauge]["value"], expected)
                    self.assertEqual(probe.objects[value]["text"], f"{expected}%")
                repeated = probe.run(probe.timer, (0x20007800,))
                self.assertFalse(any(name in ("bar_value", "arc_value", "text_fmt") for name, _ in repeated))
            probe.put(ROOT, 0)
            self.assertEqual(probe.run(probe.timer, (0x20007800,)), [])

    def test_every_partial_allocation_cleans_all_owned_objects_and_keeps_native_rows_visible(self):
        for failed in range(1, 25):
            probe = self.probe(FULL, construct=False)
            native = {address for address, obj in probe.objects.items() if obj["alive"]}
            probe.fail_at = failed
            probe.run(probe.constructor, (probe.word(0x200005D8), 2), RETURN_VALUE)
            self.assertEqual(probe.objects[probe.word(PANEL)]["children"], [])
            self.assertEqual({address for address, obj in probe.objects.items() if obj["alive"]}, native)
            for slot in range(0x20000664, 0x20000694, 4):
                self.assertFalse(probe.objects[probe.word(slot)]["flags"] & 1)
            calls = probe.run(probe.timer, (0x20007800,))
            self.assertEqual([name for name, _ in calls], ["native_callback"])

    def test_wrong_ownership_type_or_count_stops_custom_update(self):
        for fault in ("container_parent", "container_class", "container_count", "child_parent", "child_class", "child_null"):
            for index in range(3):
                probe = self.probe()
                panel = probe.word(PANEL)
                container = probe.objects[panel]["children"][1]
                child = probe.objects[container]["children"][index]
                if fault == "container_parent":
                    probe.put(container + 4, probe.word(ROOT))
                elif fault == "container_class":
                    probe.put(container, BASE + 0xF1100)
                elif fault == "container_count":
                    probe.put(probe.word(container + 8) + 4, 2)
                elif fault == "child_parent":
                    probe.put(child + 4, panel)
                elif fault == "child_class":
                    probe.put(child, 0)
                else:
                    probe.put(probe.word(probe.word(container + 8)) + index * 4, 0)
                calls = probe.run(probe.timer, (0x20007800,))
                self.assertEqual([name for name, _ in calls], ["native_callback"])

    def test_native_cleanup_and_page_switch_do_not_leave_custom_updates(self):
        probe = self.probe()
        probe.cpu.mem_write(PAGE, b"\2")
        self.assertEqual(probe.run(probe.timer, (0x20007800,)), [])
        probe.cpu.mem_write(PAGE, b"\1")
        old_root = probe.word(ROOT)
        probe.allowed_native = [(BASE + 0x59B50, BASE + 0x59BB4)]
        probe.run(BASE + 0x59B50)
        self.assertFalse(probe.objects[old_root]["alive"])
        self.assertEqual(probe.word(ROOT), 0)
        probe.allowed_native = []
        self.assertEqual(probe.run(probe.timer, (0x20007800,)), [])
        probe.prepare_home()
        probe.run(probe.constructor, (probe.word(0x200005D8), 2), RETURN_VALUE)
        probe.run(probe.timer, (0x20007800,))


@unittest.skipUnless(HAVE_ARM, "optional capstone/unicorn packages not installed")
@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class NativeWidgetTests(unittest.TestCase):
    """Execute vendor functions, separately from the generated-code model.

    Arc invalidation and renderer event dispatch are stubbed. The clipping
    rectangle, class inheritance, range and angle arithmetic execute natively;
    pixel drawing, theme styling, scheduler and heap allocation do not.
    """

    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if hashlib.sha256(cls.original).hexdigest() != SOURCE_SHA:
            raise ValueError("Exact supported firmware required")

    def machine(self):
        cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
        cpu.mem_map(0x08000000, 0x100000)
        cpu.mem_map(RAM, 0x20000)
        cpu.mem_map(STOP, 0x1000)
        cpu.mem_write(BASE, self.original)
        return cpu

    def call(self, cpu, offset, *args):
        cpu.reg_write(UC_ARM_REG_SP, STACK)
        cpu.reg_write(UC_ARM_REG_LR, STOP | 1)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            cpu.reg_write(register, value & 0xFFFFFFFF)
        cpu.emu_start((BASE + offset) | 1, STOP, count=50000)
        self.assertEqual(cpu.reg_read(UC_ARM_REG_PC), STOP)
        self.assertEqual(cpu.reg_read(UC_ARM_REG_SP), STACK)
        return cpu.reg_read(UC_ARM_REG_R0)

    @staticmethod
    def api_return(cpu, result=0):
        target = cpu.reg_read(UC_ARM_REG_LR)
        for register in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12):
            cpu.reg_write(register, 0xA5A5A5A5)
        cpu.reg_write(UC_ARM_REG_R0, result)
        cpu.reg_write(UC_ARM_REG_PC, target)

    def test_native_classes_do_not_auto_join_default_focus_group(self):
        cpu, obj = self.machine(), RAM + 0x4000
        # Real class pointers from native constructors, including inheritance.
        for name, class_pointer in (("object", 0x0809B558), ("label", 0x0809BE48),
                                    ("bar", 0x0809BD68), ("arc", 0x0809BD4C)):
            with self.subTest(widget=name):
                cpu.mem_write(obj, struct.pack("<I", class_pointer))
                self.assertEqual(self.call(cpu, 0x4EE50, obj), 0)

    def test_native_arc_range_getter_and_standard_mode_angles(self):
        cpu, obj = self.machine(), RAM + 0x4000
        cpu.mem_write(obj + 0x34, struct.pack("<H", 6))
        intercepted = []

        def hook(machine, address, size, _):
            # Invalidation, tick, flags and style attachment are outside this
            # arithmetic test; constructor initialization itself is executed.
            if address - BASE in (0x4ED80, 0x3E1E0, 0x3E2AC, 0x53C8E,
                                  0x4B62E, 0x4C070, 0x50038):
                intercepted.append(address - BASE)
                self.api_return(machine)

        cpu.hook_add(UC_HOOK_CODE, hook)
        self.call(cpu, 0x3F140, 0x0809BD4C, obj)
        self.assertEqual(struct.unpack("<H", bytes(cpu.mem_read(obj + 0x34, 2)))[0] & 6, 0)
        self.call(cpu, 0x3F8CE, obj, 180, 360)
        self.call(cpu, 0x3FA78, obj, -120, 120)
        # Exhaust the represented range and both clamps; execute native setters,
        # interpolation and getter, rather than trusting the builder's constants.
        for raw in [-32767, -200] + list(range(-120, 121)) + [200, 32767]:
            self.call(cpu, 0x3FB60, obj, raw)
            expected = max(-120, min(120, raw))
            self.assertEqual(signed(self.call(cpu, 0x3F8A8, obj)), expected)
            start, end = struct.unpack("<HH", bytes(cpu.mem_read(obj + 0x26, 4)))
            self.assertEqual((start, end), (180, 180 + (expected + 120) * 180 // 240))
        self.assertTrue(intercepted)

        # Use the mode bits written by an actual generated dashboard with all
        # six channels in semicircles, then execute the vendor's angle math.
        centered=custom.current_layout(SEMIS)
        probe=CustomArmTests.probe(self,centered)
        for container in probe.objects[probe.word(PANEL)]['children']:
            gauge=probe.objects[container]['children'][0]
            self.assertTrue(probe.objects[gauge].get('centered_mode'))
            self.assertEqual(probe.word(gauge+0x34)&6,2)
        self.call(cpu,0x3F140,0x0809BD4C,obj)
        flags=int.from_bytes(cpu.mem_read(obj+0x34,2),'little')
        cpu.mem_write(obj+0x34,((flags & ~6) | (probe.word(gauge+0x34)&6)).to_bytes(2,'little'))
        self.call(cpu,0x3F8CE,obj,180,360);self.call(cpu,0x3FA78,obj,-120,120)
        for value in (0,-120,120,0,*range(-120,121)):
            self.call(cpu,0x3FB60,obj,value)
            position=180+(value+120)*180//240
            self.assertEqual(struct.unpack('<HH',bytes(cpu.mem_read(obj+0x26,4))),
                             (min(position,270),max(position,270)))

    def test_native_renderer_clips_arc_children_when_overflow_is_clear(self):
        for overflow in (False, True):
            cpu = self.machine()
            context, clip = RAM + 0x4000, RAM + 0x4020
            parent, child = RAM + 0x10000, RAM + 0x10100
            spec, children = RAM + 0x5000, RAM + 0x5100
            cpu.mem_write(context + 8, struct.pack("<I", clip))
            cpu.mem_write(clip, struct.pack("<4h", 0, 0, 239, 319))
            cpu.mem_write(parent + 8, struct.pack("<I", spec))
            cpu.mem_write(spec, struct.pack("<II", children, 1))
            cpu.mem_write(children, struct.pack("<I", child))
            cpu.mem_write(parent + 0x14, struct.pack("<4hI", 20, 200, 90, 249, 0x80000 if overflow else 0))
            cpu.mem_write(child + 4, struct.pack("<I", parent))
            cpu.mem_write(child + 0x14, struct.pack("<4hI", 21, 200, 88, 267, 0))
            observed = []

            def hook(machine, address, size, _):
                if address == BASE + 0x2FCCA:  # No shadow/outline extends the test object.
                    self.api_return(machine, 0)
                elif address == BASE + 0x46560:  # Observe, do not execute drawing events.
                    obj, event, ctx = (machine.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
                    if event == 0x15:
                        pointer, = struct.unpack("<I", bytes(machine.mem_read(ctx + 8, 4)))
                        observed.append((obj, struct.unpack("<4h", bytes(machine.mem_read(pointer, 8)))))
                    self.api_return(machine, 0)

            cpu.hook_add(UC_HOOK_CODE, hook)
            self.call(cpu, 0x511E8, context, parent)
            self.assertEqual(observed, [(parent, (20, 200, 90, 249)),
                                        (child, (21, 200, 88, 267 if overflow else 249))])
            self.assertEqual(struct.unpack("<I", bytes(cpu.mem_read(context + 8, 4)))[0], clip)


if __name__ == "__main__":
    unittest.main()
