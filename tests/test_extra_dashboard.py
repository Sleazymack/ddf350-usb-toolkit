"""New native presets, actual firmware generation and emulated live controls."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import dashboard_faces as faces
import dashboard_fullscreen as lcd
import installer
import patch_firmware as patcher
from test_dashboard_zones import HAVE_ARM, ROOT
from test_dashboard_six import RAM
from test_installer import raw_fixture


class ExtraArtworkTests(unittest.TestCase):
    def test_presets_are_distinct_native_fullscreen_with_all_live_values(self):
        self.assertEqual(tuple(edition[0] for edition in app.EDITIONS[-3:]), lcd.EXTRA_THEMES)
        outputs = []
        for key in lcd.EXTRA_THEMES:
            scene = lcd.scene(key)
            self.assertEqual({item['channel'] for item in scene if item.get('role') == 'cache'}, set(range(5)))
            outputs.append(hashlib.sha256(lcd.render(key).tobytes()).hexdigest())
            self.assertNotEqual(lcd.render(key, {1: -100, 2: 100, 3: -100, 4: 100}).tobytes(), lcd.render(key).tobytes())
            self.assertEqual(lcd.render(key).size, (240, 320))
            for schema in (5, 7, 8):
                with self.assertRaises(ValueError):
                    lcd.validate({'schema': schema, 'theme': key})
        self.assertEqual(len(set(outputs)), 3)

    def test_equalizer_segments_start_at_neutral_on_primary_channels(self):
        segments = [item for item in lcd.scene(lcd.EXTRA_THEMES[0]) if item.get('role') == 'segment']
        for channel in (1, 2):
            self.assertEqual([item['slot'] for item in segments if item['channel'] == channel], list(range(16)))
        self.assertEqual(faces.center_edge(0), 8)
        self.assertEqual(faces.center_edge(-100), 0)
        self.assertEqual(faces.center_edge(100), 16)

    def test_refined_digits_have_one_ink_color_and_are_not_clipped(self):
        bank = faces.face_bank(True, True, native=True)
        for key in lcd.EXTRA_THEMES:
            for channel in range(5):
                for index, character in enumerate(faces.SIGNED_CHARS):
                    if channel == 0 and character == '+':
                        continue
                    image = faces.bitmap(key, f'd{channel}_{index}', True, True, native=True)
                    colors = {color for color in image.getdata() if color[3]}
                    self.assertLessEqual(len(colors), 1, (key, channel, character))
                    if character.isdigit():
                        left, top, right, bottom = image.getbbox()
                        self.assertGreater(top, 0)
                        self.assertLess(bottom, image.height)


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'), 'Local official firmware required')
class ExtraFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()

    def test_074_installed_presets_remain_exactly_recognized_and_replaceable(self):
        hashes = json.loads(Path(__file__).with_name('legacy-074-extra-faces.json').read_text())
        for old_key, current_key in zip(lcd.LEGACY_EXTRA_THEMES, lcd.EXTRA_THEMES):
            for fast in (False, True):
                previous = patcher.build_patch(self.original, dashboard=old_key, usb_1ms=fast)
                self.assertEqual(patcher.sha256(previous), hashes[old_key][int(fast)])
                current = patcher.build_patch(self.original, dashboard=current_key, usb_1ms=fast)
                after, _, _ = installer.plan_transfer(raw_fixture(previous), current, self.original)
                self.assertEqual(after[installer.APP:installer.APP + len(current)], current)

    def test_switch_to_each_new_preset_and_return_to_stock(self):
        from test_installer_switching import windows_prefix
        from test_startup_animation import asset
        for fast in (False, True):
            before = raw_fixture(self.original)
            for key in lcd.EXTRA_THEMES:
                target = patcher.build_patch(self.original, dashboard=key, usb_1ms=fast)
                self.assertLess(len(target), lcd.f.PLAYER_OFFSET)
                self.assertEqual(patcher.revert_patch(target), self.original)
                self.assertTrue(patcher.inspect_image(target)['recognized'])
                after, _, _ = installer.plan_transfer(windows_prefix(before), target, self.original)
                self.assertEqual(after[installer.APP:installer.APP + len(target)], target)
                before = after
                photo = patcher.build_patch(self.original, dashboard=key, startup_photo=bytes(patcher.photo.PIXELS))
                self.assertEqual(patcher.revert_patch(photo), self.original)
                animated = patcher.build_patch(self.original, dashboard=key, startup_animation=asset())
                self.assertTrue(patcher.inspect_image(animated)['recognized'])
            restored, _, _ = installer.plan_transfer(before, self.original, self.original)
            self.assertEqual(restored[installer.APP:installer.APP + len(self.original)], self.original)

    @unittest.skipUnless(HAVE_ARM, 'Independent CPU emulator required')
    def test_emulated_extremes_neutral_and_needles_use_the_actual_channel_values(self):
        from test_fullscreen_dashboard import FullscreenTests
        for key in lcd.EXTRA_THEMES:
            image = patcher.build_patch(self.original, dashboard=key, usb_1ms=True)
            probe = FullscreenTests.probe(self, image, True)
            children = probe.objects[probe.objects[probe.word(ROOT)]['children'][-1]]['children']
            widgets = [(item, probe.objects[node]) for item, node in zip(lcd.scene(key), children)]
            for raw, percent in ((-2100, -100), (0, 0), (2100, 100)):
                probe.cpu.mem_write(RAM + 0x204, struct.pack('<4i', *([raw] * 4)))
                probe.run(probe.timer, (0x20007800,))
                for item, widget in widgets:
                    if item.get('role') == 'cache' and item['channel']:
                        self.assertEqual(widget['value'], percent)
                    if item.get('role') == 'needle':
                        self.assertEqual(widget['points'], faces.points(item['geom'], (percent + 100) // 2))
                    if item.get('role') == 'segment':
                        edge = faces.center_edge(percent)
                        self.assertEqual(not bool(widget['flags'] & 1), min(8, edge) <= item['slot'] < max(8, edge))


if __name__ == '__main__':
    unittest.main()
