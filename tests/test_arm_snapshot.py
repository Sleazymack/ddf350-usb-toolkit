"""Optional, independent ARM checks. No USB access and no firmware distribution.

Set DDF350_OFFICIAL_FIRMWARE to the exact supported local input and install the
optional packages in requirements-arm.txt. These are bounded CPU simulations,
not electrical, scheduler, RF, stack-headroom, or hardware stability tests.
"""
import hashlib
import os
from pathlib import Path
import random
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import patch_firmware as patcher

try:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
    from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS,
                         UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE)
    from unicorn.arm_const import (
        UC_CPU_ARM_CORTEX_M3, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
        UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
        UC_ARM_REG_R11, UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR,
        UC_ARM_REG_APSR, UC_ARM_REG_PRIMASK, UC_ARM_REG_PC,
    )
    HAVE_ARM = True
except ImportError:
    HAVE_ARM = False

BASE = 0x08005000
ORIGINAL_SIZE = 626956
ORIGINAL_SHA = "06c47e22049f0ec91823156b3a1afb997dfe31309d06c493aab08426d2866bbc"
FAST_SHA = "9afd478afc6085b48435816273f844ff277facbb48d7116f5bfe84daa0cbf250"
SOURCE = 0x200001A0
REPORT = 0x200073B4
SP = 0x2001F000
START = BASE + 0x2C8A2
END = BASE + 0x2C97C
HELPER = BASE + ORIGINAL_SIZE


def packed(values):
    return sum(x << (11 * i) for i, x in enumerate(values)).to_bytes(22, "little")


def report_oracle(values):
    buttons = int(values[14] > 896) | (int(values[15] > 896) << 1)
    return bytes([buttons]) + struct.pack("<8H", *values[:8])


@unittest.skipUnless(HAVE_ARM, "optional capstone/unicorn packages not installed")
@unittest.skipUnless(os.environ.get("DDF350_OFFICIAL_FIRMWARE"), "local official input not supplied")
class ArmSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ["DDF350_OFFICIAL_FIRMWARE"]).read_bytes()
        if len(cls.original) != ORIGINAL_SIZE or hashlib.sha256(cls.original).hexdigest() != ORIGINAL_SHA:
            raise ValueError("DDF350_OFFICIAL_FIRMWARE must be the exact supported official image")
        cls.fast = patcher.build_patch(cls.original, usb_1ms=True)
        cls.decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        cls.decoder.detail = True
        cls.registers = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                         UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                         UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
                         UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_APSR]

    def run_decoder(self, data, values, primask=0, request=None, replacement=None):
        u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
        u.mem_map(0x08000000, 0x100000)
        u.mem_write(BASE, data)
        u.mem_map(0x20000000, 0x20000)
        u.mem_write(SOURCE, packed(values))
        u.mem_write(REPORT, b"\xA5" * 32)
        u.mem_write(SP - 96, b"\xCC" * 128)
        for index, reg in enumerate(self.registers[:-1]):
            u.reg_write(reg, 0x31410000 + index * 0x111)
        u.reg_write(UC_ARM_REG_SP, SP)
        u.reg_write(UC_ARM_REG_R4, REPORT)
        u.reg_write(UC_ARM_REG_LR, 0x080F8001)
        u.reg_write(UC_ARM_REG_PRIMASK, primask)
        u.reg_write(UC_ARM_REG_APSR, 0xA0000000)
        seen, reads = [], []
        pending, delivered = False, None

        def on_code(uc, address, size, _):
            nonlocal pending, delivered
            if address == END:
                uc.emu_stop()
                return
            self.assertTrue(START <= address < END or HELPER <= address < BASE + len(data) - 4)
            seen.append((address, uc.reg_read(UC_ARM_REG_PRIMASK)))
            if request == address:
                pending = True
            if pending and delivered is None and uc.reg_read(UC_ARM_REG_PRIMASK) == 0:
                # A complete producer at an unmasked boundary; not a real ISR,
                # host schedule, DMA writer, NMI, or wall-clock timing model.
                uc.mem_write(SOURCE, packed(replacement))
                delivered = address

        def on_read(uc, access, address, size, value, _):
            if SOURCE <= address < SOURCE + 22:
                self.assertLessEqual(address + size, SOURCE + 22)
                reads.append((address, size, uc.reg_read(UC_ARM_REG_PRIMASK)))
            else:
                self.assertTrue((BASE <= address and address + size <= BASE + len(data))
                                or (REPORT <= address and address + size <= REPORT + 17)
                                or (SP - 48 <= address and address + size <= SP))

        def on_write(uc, access, address, size, value, _):
            self.assertTrue((REPORT <= address and address + size <= REPORT + 17)
                            or (SP - 48 <= address and address + size <= SP))

        u.hook_add(UC_HOOK_CODE, on_code)
        u.hook_add(UC_HOOK_MEM_READ, on_read)
        u.hook_add(UC_HOOK_MEM_WRITE, on_write)
        u.emu_start(START | 1, 0, count=400)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), END)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), SP)
        self.assertEqual(u.reg_read(UC_ARM_REG_PRIMASK), primask)
        self.assertEqual(bytes(u.mem_read(SP - 96, 48)), b"\xCC" * 48)
        self.assertEqual(bytes(u.mem_read(SP, 32)), b"\xCC" * 32)
        self.assertEqual(bytes(u.mem_read(REPORT + 17, 15)), b"\xA5" * 15)
        if data is self.fast:
            self.assertEqual(reads, [(SOURCE + i, 4, 1) for i in (0, 4, 8, 12, 16)]
                             + [(SOURCE + 20, 2, 1)])
            self.assertTrue(all(mask == primask for address, mask in seen if address >= HELPER + 42))
            if primask == 0:
                self.assertEqual(sum(mask == 1 for _, mask in seen), 13)
        return bytes(u.mem_read(REPORT, 17)), [u.reg_read(r) for r in self.registers], seen, delivered

    def test_helper_relocation_and_native_body(self):
        self.assertEqual(hashlib.sha256(self.fast).hexdigest(), FAST_SHA)
        self.assertEqual(len(self.fast), ORIGINAL_SIZE + 276)
        helper = list(self.decoder.disasm(self.fast[ORIGINAL_SIZE:-4], HELPER))
        native = list(self.decoder.disasm(self.original[0x2C8A2:0x2C97C], START))
        relocated = {i.address: i for i in helper}
        replacements = 0
        for instruction in native:
            actual = relocated[HELPER + 42 + instruction.address - START]
            pc_memory = [o for o in instruction.operands if o.type == ARM_OP_MEM and o.mem.base == ARM_REG_PC]
            if pc_memory:
                self.assertEqual((actual.mnemonic, actual.op_str), ("mov", "r0, sp"))
                literal = ((instruction.address + 4) & ~3) + pc_memory[0].mem.disp - BASE
                self.assertEqual(struct.unpack_from("<I", self.original, literal)[0], SOURCE)
                replacements += 1
            else:
                self.assertEqual(actual.bytes, instruction.bytes)
                if instruction.mnemonic in {"b", "beq", "bne", "bge", "ble", "bgt", "blt",
                                             "bhi", "bls", "bhs", "blo", "bpl", "bmi", "bvc", "bvs"}:
                    self.assertEqual(actual.operands[0].type, ARM_OP_IMM)
                    self.assertEqual(actual.operands[0].imm - (HELPER + 42), instruction.operands[0].imm - START)
        self.assertEqual(replacements, 10)
        hook = list(self.decoder.disasm(self.fast[0x2C8A2:0x2C8A8], START))
        self.assertEqual(hook[0].mnemonic, "b.w")
        self.assertEqual(hook[0].operands[0].imm, HELPER)
        branches = [i for i in helper if i.mnemonic == "b.w"]
        self.assertEqual(branches[-1].operands[0].imm, END)

    def test_payload_abi_and_primask_against_native(self):
        rng = random.Random(3501000)
        vectors = [[v] * 16 for v in (0, 1, 895, 896, 897, 1023, 2046, 2047)]
        vectors += [[rng.randrange(2048) for _ in range(16)] for _ in range(20)]
        for mask in (0, 1):
            for index, values in enumerate(vectors):
                with self.subTest(primask=mask, vector=index):
                    native = self.run_decoder(self.original, values, mask)
                    fast = self.run_decoder(self.fast, values, mask)
                    self.assertEqual(native[0], report_oracle(values))
                    self.assertEqual(fast[0], native[0])
                    self.assertEqual(fast[1], native[1])

    def test_snapshot_atomic_at_each_instruction_boundary(self):
        initial = [100, 200, 300, 400, 500, 600, 700, 800] + [0] * 8
        replacement = [1900, 1800, 1700, 1600, 1500, 1400, 1300, 1200] + [2047] * 8
        baseline = self.run_decoder(self.fast, initial)
        for mask in (0, 1):
            for site, _ in baseline[2]:
                with self.subTest(primask=mask, site=hex(site)):
                    result = self.run_decoder(self.fast, initial, mask, site, replacement)
                    self.assertIn(result[0], (report_oracle(initial), report_oracle(replacement)))
                    if mask:
                        self.assertIsNone(result[3])
                        self.assertEqual(result[0], report_oracle(initial))

    def test_ready_cleared_before_tx_valid_call(self):
        code = list(self.decoder.disasm(self.fast[0x2C986:0x2C992], BASE + 0x2C986))
        self.assertEqual([i.mnemonic for i in code], ["movs", "ldr", "strb", "movs", "bl"])
        self.assertEqual(code[0].op_str, "r0, #0")
        self.assertEqual(code[2].op_str, "r0, [r1]")
        self.assertEqual(code[3].op_str, "r0, #1")
        self.assertEqual(code[-1].operands[0].imm, BASE + 0x2918C)
        pointer = ((code[1].address + 4) & ~3) + code[1].operands[1].mem.disp - BASE
        self.assertEqual(struct.unpack_from("<I", self.fast, pointer)[0], 0x2000018C)


if __name__ == "__main__":
    unittest.main()
