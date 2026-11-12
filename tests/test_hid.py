"""Offline fixtures only: no Tk window, Windows API, enumeration or radio access."""
import struct
import unittest
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pc'))

from ddf350_hid import decode_report, Channels, HIDP_CAPS, HIDD_ATTRIBUTES, C


def fixture(ch1,ch2,prefix=0,buttons=3):
    return bytes([prefix,buttons])+struct.pack('<8H',ch1,ch2,7,42,1023,2047,1,512)


class DecoderTests(unittest.TestCase):
    def test_zero_id_and_real_channel_offsets(self):
        self.assertEqual(decode_report(fixture(0x0123,0x0456)),Channels(291,1110))

    def test_button_byte_does_not_shift_channels(self):
        for buttons in range(4):
            self.assertEqual(decode_report(fixture(123,1456,buttons=buttons)),Channels(123,1456))

    def test_independent_firmware_emulation_reports(self):
        # Frozen output of native ARM execution, not manufactured by this fixture.
        source=Path(__file__).resolve().parent/'fixtures/native_reports.json'
        audit=json.loads(source.read_text(encoding='utf-8'))
        self.assertEqual(audit['source_sha256'],'f58e039f1c79fa9e693bcef5a46c758f7439da1275df0f8233d1ad2ce7fd539f')
        cases=audit['cases']
        self.assertEqual(len(cases),47)
        for index,case in enumerate(cases):
            if not case['send_path']: continue
            with self.subTest(case=index):
                report=b'\0'+bytes.fromhex(case['report'])
                self.assertEqual(decode_report(report),Channels(*case['slots'][:2]))

    def test_center_and_limits(self):
        for pair in ((0,0),(1023,1023),(2047,2047),(0,2047),(2047,0)):
            with self.subTest(pair=pair):
                self.assertEqual(decode_report(fixture(*pair)),Channels(*pair))

    def test_reject_wrong_lengths_including_native_17(self):
        good=fixture(1,2)
        for length in (0,1,4,16,17,19,64):
            with self.subTest(length=length),self.assertRaises(ValueError):
                decode_report((good+b'\0'*64)[:length])

    def test_reject_nonzero_report_id(self):
        for report_id in (1,17,255):
            with self.subTest(report_id=report_id),self.assertRaises(ValueError):
                decode_report(fixture(1023,1023,report_id))

    def test_reject_out_of_range_without_clamping(self):
        for pair in ((2048,0),(0,2048),(65535,1023),(1023,65535)):
            with self.subTest(pair=pair),self.assertRaises(ValueError):
                decode_report(fixture(*pair))

    def test_bytes_like_and_type_rejection(self):
        for value in (bytearray(fixture(10,20)),memoryview(fixture(10,20))):
            self.assertEqual(decode_report(value),Channels(10,20))
        with self.assertRaises(TypeError): decode_report('aucune donnée')

    def test_structures_required_by_hid_contract(self):
        self.assertEqual(C.sizeof(HIDP_CAPS),64)
        self.assertEqual(C.sizeof(HIDD_ATTRIBUTES),12)


if __name__=='__main__':
    unittest.main(verbosity=2)
