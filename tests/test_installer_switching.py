"""Successive dashboard changes, including both Windows SVI entry orders.

All transfer planning is offline. Fixtures contain synthetic directory entries
and optional, locally supplied firmware; no device is opened.
"""
import json
import os
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import installer as i
import patch_firmware as p
from test_installer import raw_fixture


def short(name,attribute,cluster,size=0):
    entry=bytearray(32)
    entry[:11]=name;entry[11]=attribute
    struct.pack_into('<H',entry,26,cluster)
    struct.pack_into('<I',entry,28,size)
    return entry


def windows_prefix(before, *, guid_first=False, wp_cluster=3):
    raw=bytearray(before)
    raw[i.APP:i.APP+0x3000]=bytes(0x3000)
    guid_cluster=7-wp_cluster
    wp_lfn=bytes.fromhex(
        '4274000000ffffffffffff0f00ceffffffffffffffffffffffff0000ffffffff'
        '01570050005300650074000f00ce740069006e00670073002e00000064006100')
    guid_lfn=bytes.fromhex(
        '42470075006900640000000f00ffffffffffffffffffffffffff0000ffffffff'
        '0149006e006400650078000f00ff6500720056006f006c00750000006d006500')
    wp_group=wp_lfn+short(b'WPSETT~1DAT',0x20,wp_cluster,12)
    guid_group=guid_lfn+short(b'INDEXE~1   ',0x20,guid_cluster,76)
    directory=short(b'.          ',0x10,2)+short(b'..         ',0x10,0)
    directory+=(guid_group+wp_group) if guid_first else (wp_group+guid_group)
    raw[i.APP:i.APP+256]=directory
    wp=i.APP+(wp_cluster-2)*i.SECTOR
    guid=i.APP+(guid_cluster-2)*i.SECTOR
    struct.pack_into('<III',raw,wp,12,1,2)
    raw[guid:guid+76]='{12345678-1234-1234-1234-123456789ABC}'.encode('utf-16le')
    return bytes(raw)


class MetadataOrderTests(unittest.TestCase):
    def test_both_entry_orders_and_both_cluster_allocations(self):
        for first in (False,True):
            for cluster in (3,4):
                with self.subTest(guid_first=first,wp_cluster=cluster):
                    self.assertTrue(i.known_svi(windows_prefix(raw_fixture(b''),guid_first=first,wp_cluster=cluster)))

    def test_reordered_metadata_still_rejects_unexpected_bytes_or_payload(self):
        for first in (False,True):
            raw=windows_prefix(raw_fixture(b''),guid_first=first)
            for offset in (i.APP,i.APP+11,i.APP+0x42,i.APP+0x108,0x8000,0x800c,0x9000,0x904c):
                changed=bytearray(raw);changed[offset]^=1
                with self.subTest(order=first,offset=offset):self.assertFalse(i.known_svi(changed))


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official input not supplied')
class SwitchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        p._require_original(cls.original)
        layout=json.loads((Path(__file__).parents[1]/'examples/drift-six.json').read_text())
        cls.images=[cls.original]+[p.build_patch(cls.original,dashboard=d,usb_1ms=f)
            for d in ('original','ch1234','ch123456') for f in (False,True)]
        cls.images += [p.build_patch(cls.original,dashboard='custom',usb_1ms=f,layout=layout) for f in (False,True)]

    def test_every_source_to_target_with_each_windows_directory_order(self):
        for source in self.images:
            for first in (False,True):
                before=windows_prefix(raw_fixture(source),guid_first=first,wp_cluster=4 if first else 3)
                for target in self.images:
                    with self.subTest(source=p.sha256(source),target=p.sha256(target),guid_first=first):
                        after,offsets,state=i.plan_transfer(before,target,self.original)
                        self.assertTrue(state.endswith('/windows-prefix'))
                        self.assertEqual(after[i.APP:i.APP+len(target)],target)
                        self.assertEqual(after[:i.APP],before[:i.APP])
                        self.assertEqual(after[i.APP+len(target):],before[i.APP+len(target):])
                        self.assertEqual(offsets,tuple(sorted(offsets,reverse=True)))

    def test_successive_changes_preserve_inert_tail_and_recognize_active_image(self):
        current=raw_fixture(self.original)
        for n,image in enumerate(self.images[1:]+self.images[::-1]):
            current=windows_prefix(current,guid_first=bool(n%2),wp_cluster=3+n%2)
            current,_,_=i.plan_transfer(current,image,self.original)
            self.assertEqual(i.recognize_installed(current,self.original),p.inspect_image(image)['variant'])

    def test_metadata_does_not_authorize_any_changed_application_suffix(self):
        for first in (False,True):
            raw=bytearray(windows_prefix(raw_fixture(self.images[-1]),guid_first=first))
            raw[i.APP+0x4000]^=1
            with self.assertRaises(ValueError):i.plan_transfer(raw,self.original,self.original)


if __name__=='__main__':unittest.main()
