"""Opaque gauge cards and optional CH2 flashing, with real generated ARM code."""
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tkinter as tk
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard_custom as custom
import dashboard_fullscreen as lcd
import dashboard_gauges as gauges
import dashboard_zones as zones
import editor
import installer
import patch_firmware as patcher
import wizard
import test_dashboard_zones as zone_tests
HAVE_ARM,ZoneProbe=zone_tests.HAVE_ARM,zone_tests.ZoneProbe
from test_dashboard_six import BASE,PANEL,ROOT,RAM
from test_installer import raw_fixture


class GaugeEditorTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.withdraw()
        self.ui=editor.DashboardEditor(self.root,layout=zones.DEFAULT_LOWER,compact=True)

    def tearDown(self):
        self.root.destroy()

    def test_panel_color_changes_only_selected_gauge_and_survives_json(self):
        before=self.ui.get_layout()
        selected=self.ui._selected
        with mock.patch.object(editor.colorchooser,'askcolor',return_value=((18,52,86),'#123456')):
            self.ui.panel_color_button.invoke()
        result=self.ui.get_layout()
        self.assertEqual(result['background'],before['background'])
        for old,new in zip(before['widgets'],result['widgets']):
            if old['id']==selected:self.assertEqual(new['background'],'#123456')
            else:self.assertEqual(old,new)
        self.assertEqual(custom.parse_layout(custom.canonical_json(result)),result)

    def test_alarm_is_unchecked_by_default_and_saved_with_the_design(self):
        self.assertFalse(self.ui.get_layout()['blink_ch2'])
        self.ui.alarm_checkbox.invoke()
        self.assertTrue(self.ui.get_layout()['blink_ch2'])
        self.assertIsNotNone(self.ui._blink_after)
        self.ui.alarm_checkbox.invoke()
        self.assertFalse(self.ui.get_layout()['blink_ch2'])
        self.assertIsNone(self.ui._blink_after)

    def test_photo_does_not_remove_solid_gauge_backings(self):
        import dashboard_wallpaper
        from PIL import Image
        import io
        stream=io.BytesIO()
        Image.new('RGB',(240,320),'yellow').save(stream,format='PNG')
        self.ui._commit(self.ui.full_background(dashboard_wallpaper.convert(stream.getvalue())),'Photo')
        self.assertTrue(all(widget['background']=='#101924' for widget in self.ui.get_layout()['widgets']))
        for widget in self.ui.get_layout()['widgets']:
            if widget['kind']=='semicircle':self.assertEqual(custom.widget_parts(widget)['arc_width'],8)
        self.ui.stock_background()
        self.assertFalse(self.ui.get_layout()['full_background'])


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'Local firmware required')
class GaugeFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()

    def test_alarm_choice_and_legacy_styles_are_recognized_and_replaceable(self):
        saved=json.loads(Path(__file__).with_name('legacy-075-faces.json').read_text())
        for key in lcd.THEMES:
            for fast in (False,True):
                old=patcher.build_patch(self.original,dashboard=key,usb_1ms=fast)
                self.assertEqual(patcher.sha256(old),saved[key][int(fast)])
                current=patcher.build_patch(self.original,dashboard=key,usb_1ms=fast,blink_ch2=True)
                self.assertTrue(patcher.inspect_image(current)['recognized'])
                self.assertEqual(patcher.revert_patch(current),self.original)
                after,_,_=installer.plan_transfer(raw_fixture(old),current,self.original)
                self.assertEqual(after[installer.APP:installer.APP+len(current)],current)

    def test_alarm_state_survives_the_authoring_and_media_workflows(self):
        from test_startup_animation import asset
        for key in ('original','ch1234','ch123456',*lcd.EXTRA_THEMES):
            enabled=patcher.build_patch(self.original,dashboard=key,blink_ch2=True)
            layout=patcher.inspect_image(enabled)['layout']
            self.assertEqual(custom.current_layout(layout),layout)
            wrapped=patcher.build_patch(self.original,dashboard=key,blink_ch2=True,startup_animation=asset())
            self.assertTrue(patcher.inspect_image(wrapped)['recognized'])
            self.assertEqual(patcher.revert_patch(wrapped),self.original)

    def test_current_photo_composition_and_its_panels_roundtrip_without_losing_choices(self):
        from test_dashboard_wallpaper import design
        spec=gauges.upgrade(design())
        spec.update(blink_ch2=True,header='battery_only')
        spec['widgets'][0]['background']='#223344'
        image=patcher.build_patch(self.original,dashboard='custom',layout=spec)
        self.assertEqual(patcher.inspect_image(image)['layout'],spec)
        self.assertEqual(patcher.revert_patch(image),self.original)

    @unittest.skipUnless(HAVE_ARM,'Optional CPU emulator required')
    def test_custom_gauge_thickness_backing_and_strict_threshold(self):
        for kind in ('bar','semicircle','number'):
            original=copy.deepcopy(zones.DEFAULT_LOWER)
            original['widgets']=[dict(id='g2',channel=2,kind=kind,zone='B',col=0,row=0,color='#ffcc33')]
            spec=gauges.upgrade(original)
            spec['blink_ch2']=True
            probe=zone_tests.ZoneFirmwareTests.scene(self,spec)
            container=probe.objects[probe.word(PANEL)]['children'][0]
            gauge,title,value=probe.objects[container]['children']
            self.assertEqual(probe.objects[container]['styles'][(0x21,0)],255)
            self.assertEqual(probe.objects[container]['colors'][('bg_color',0)],custom.native_color('#101924'))
            if kind=='semicircle':self.assertEqual(probe.objects[gauge]['styles'][(0x850,0x20000)],8)
            if kind=='bar':self.assertEqual(probe.objects[gauge]['size'][1],12)
            for raw,percent in ((1485,90),(1502,91),(1650,100),(-1650,-100),(0,0)):
                for stamp in (0,125,250,375,500):
                    probe.cpu.mem_write(RAM+0x208,struct.pack('<i',raw))
                    probe.put(RAM+0x7804,stamp)
                    probe.run(probe.timer,(RAM+0x7800,))
                    hidden=percent>90 and bool(stamp//125%2)
                    self.assertEqual(bool(probe.objects[value]['flags']&1),hidden)
                    self.assertEqual(bool(probe.objects[gauge]['flags']&1),True if kind=='number' else hidden)
                    self.assertFalse(probe.objects[title]['flags']&1)
                    self.assertFalse(probe.objects[container]['flags']&1)
                    self.assertEqual(probe.objects[gauge]['value'],percent)
                    self.assertEqual(probe.objects[value]['text'],f'{percent}%')

    @unittest.skipUnless(HAVE_ARM,'Optional CPU emulator required')
    def test_graphic_gauges_restore_lit_segments_after_each_flash(self):
        from test_fullscreen_dashboard import FullscreenTests
        for key in lcd.EXTRA_THEMES:
            image=patcher.build_patch(self.original,dashboard=key,blink_ch2=True)
            probe=FullscreenTests.probe(self,image)
            children=probe.objects[probe.objects[probe.word(ROOT)]['children'][-1]]['children']
            pairs=list(zip(lcd.scene(key),children))
            for stamp in (0,125,250,375,500):
                probe.cpu.mem_write(RAM+0x208,struct.pack('<i',1650))
                probe.put(RAM+0x7804,stamp)
                probe.run(probe.timer,(RAM+0x7800,))
                hidden=bool(stamp//125%2)
                for item,node in pairs:
                    if item.get('channel')==2 and item.get('role') in ('digit','percent'):
                        self.assertEqual(bool(probe.objects[node]['flags']&1),hidden)
                    if item.get('channel')==2 and item.get('role')=='segment':
                        self.assertEqual(not bool(probe.objects[node]['flags']&1),not hidden and item['slot']>=8)

    @unittest.skipUnless(HAVE_ARM,'Optional CPU emulator required')
    def test_closing_home_during_the_native_callback_prevents_alarm_access(self):
        spec=gauges.upgrade(zones.DEFAULT_LOWER)
        spec['blink_ch2']=True
        probe=zone_tests.ZoneFirmwareTests.scene(self,spec)
        probe.native_callback_action=lambda machine:machine.put(ROOT,0)
        probe.put(RAM+0x7804,125)
        calls=probe.run(probe.timer,(RAM+0x7800,))
        self.assertEqual([name for name,_ in calls],['native_callback'])
        self.assertFalse(any(address==RAM+0x7804 for address,_ in probe.reads))

    @unittest.skipUnless(HAVE_ARM,'Optional CPU emulator required')
    def test_native_presets_flash_only_ch2_when_enabled(self):
        from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
        for key in ('original','ch1234','ch123456'):
            image=patcher.build_patch(self.original,dashboard=key,blink_ch2=True)
            probe=ZoneProbe(self,image,patcher.ORIGINAL_SIZE)
            if key=='ch123456':
                decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
                decoder.detail=True
                entry=next(decoder.disasm(image[0x59ae4:0x59ae8],BASE+0x59ae4)).operands[0].imm
                probe.run(entry,(probe.word(0x200005d8),2))
            callback=struct.unpack_from('<I',image,0x5850c)[0]
            bar=probe.objects[probe.word(0x20000688)]
            value=probe.objects[probe.word(0x20000670)]
            for percent in (90,91,100,-100,0):
                for stamp in (0,125,250):
                    bar['value']=percent
                    probe.put(RAM+0x7804,stamp)
                    probe.run(callback,(RAM+0x7800,))
                    expected=percent>90 and bool(stamp//125%2)
                    self.assertEqual(bool(bar['flags']&1),expected)
                    self.assertEqual(bool(value['flags']&1),expected)
                    self.assertFalse(probe.objects[probe.word(0x20000684)]['flags']&1)


if __name__=='__main__':unittest.main()
