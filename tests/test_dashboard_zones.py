"""Two-zone contracts, UI movement, actual Thumb with modeled native objects."""
import copy
import hashlib
import itertools
import os
from pathlib import Path
import struct
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard_custom as c
import dashboard_zones as z
import editor
import app
import wizard
import i18n
import patch_firmware as p
from test_dashboard_custom import CustomProbe,HAVE_ARM,BASE,ROOT,PANEL,RETURN_VALUE,percentage


class LayoutTests(unittest.TestCase):
    def test_strict_zones_bounds_collisions_and_geometry(self):
        good=z.validate(z.DEFAULT)
        for item in good['widgets']:
            x,y,w,h=c.rectangle(item)
            self.assertGreaterEqual(x,0);self.assertLessEqual(x+w,215)
            if item['zone']=='A':self.assertLessEqual(y+h,150)
            else:self.assertTrue(170<=y and y+h<=270)
            self.assertEqual(editor.widget_bounds(item),(20+x,30+y,20+x+w,30+y+h))
        for field,value in [('zone','C'),('zone',True),('row',6),('col',5),('kind','script'),('channel',1)]:
            bad=copy.deepcopy(good);bad['widgets'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):z.validate(bad)
        bad=copy.deepcopy(good);bad['widgets'][1]['row']=0
        with self.assertRaises(ValueError):z.validate(bad)
        legacy=copy.deepcopy(editor.DEFAULT_LAYOUT)
        self.assertEqual(c.validate_layout(legacy)['schema'],1)
        self.assertEqual(c.parse_layout(c.canonical_json(good)),good)

    def test_legacy_import_keeps_only_lower_grid_and_rejects_drag_into_stock_top(self):
        root=tk.Tk();root.withdraw();ui=editor.DashboardEditor(root,layout=z.DEFAULT,compact=True)
        try:
            self.assertEqual(ui.get_layout()['schema'],6)
            self.assertEqual({w['channel'] for w in ui.get_layout()['widgets']},{3,4})
            self.assertFalse(hasattr(ui,'zone_combo'))
            ui._selected='g3';ui._sync_controls()
            box=editor.widget_bounds(ui._selected_widget())
            def event(x,y):return SimpleNamespace(x=ui.origin[0]+x*ui.scale,y=ui.origin[1]+y*ui.scale)
            before=ui.get_layout();ui._press(event(box[0]+4,box[1]+4));ui._release(event(24,34))
            self.assertEqual(ui.get_layout(),before)
            self.assertTrue(ui.move_selected(0,1))
            ui.set_layout(before);self.assertEqual(ui.get_layout(),before)
            only_a={**z.DEFAULT,'widgets':[z.DEFAULT['widgets'][0]]}
            with self.assertRaises(ValueError):ui.set_layout(only_a)
            self.assertEqual(ui.get_layout(),before)
        finally:ui.destroy();root.destroy()

    def test_compact_controls_visible_in_all_editor_tabs_fr_and_en(self):
        for language in ('fr','en'):
            i18n.set_language(language)
            root=tk.Tk();root.attributes('-alpha',0);ui=wizard.Wizard(root)
            try:
                ui.choose_custom();root.update();e=ui.inline_editor
                for tab in e.notebook.tabs():
                    e.notebook.select(tab);root.update()
                    def check(parent):
                        for child in parent.winfo_children():
                            if child.winfo_ismapped():
                                x=child.winfo_rootx()-root.winfo_rootx();y=child.winfo_rooty()-root.winfo_rooty()
                                self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                                self.assertLessEqual(x+child.winfo_width(),root.winfo_width())
                                self.assertLessEqual(y+child.winfo_height(),root.winfo_height())
                                check(child)
                    check(e)
                self.assertLessEqual(ui.forward.winfo_rooty()-root.winfo_rooty()+ui.forward.winfo_height(),root.winfo_height())
            finally:ui.close();i18n.set_language('fr')


if HAVE_ARM:
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
    class ZoneProbe(CustomProbe):
        def prepare_home(self):
            root=super().prepare_home()
            for pointer in z.UPPER_NATIVE:
                if not self.word(pointer):self.put(pointer,self.allocate('label',root))
            return root


@unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local input and optional ARM packages required')
class ZoneFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();p._require_original(cls.original)
    def scene(self,spec=None,construct=True):
        image=p.build_patch(self.original,dashboard='custom',layout=spec or z.DEFAULT)
        decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);decoder.detail=True
        constructor=next(decoder.disasm(image[0x59ae4:0x59ae8],BASE+0x59ae4)).operands[0].imm
        timer=struct.unpack_from('<I',image,0x5850c)[0]
        scene=ZoneProbe(self,image,p.ORIGINAL_SIZE);scene.constructor=constructor;scene.timer=timer
        if construct:scene.run(constructor,(scene.word(0x200005d8),2),RETURN_VALUE)
        return scene
    def test_layout_scope_values_native_battery_and_original_menu_button(self):
        scene=self.scene();panel=scene.word(PANEL);native_battery=scene.word(0x200005cc)
        self.assertEqual(scene.objects[panel]['size'],(215,270))
        self.assertEqual(scene.objects[panel]['align'],(1,20,30))
        self.assertFalse(scene.objects[scene.word(0x200005d8)]['flags']&1)
        for pointer in z.UPPER_NATIVE:self.assertTrue(scene.objects[scene.word(pointer)]['flags']&1)
        for n in range(4):
            raw=[-1111,777,1200,-1800,0,0];scene.cpu.mem_write(0x20000204,struct.pack('<6i',*raw))
            scene.objects[native_battery]['value']=n*31
            scene.run(scene.timer,(0x20007800,))
            for item,container in zip(z.validate(z.DEFAULT)['widgets'],scene.objects[panel]['children']):
                gauge,title,value=scene.objects[container]['children']
                expected=n*31 if item['kind']=='battery' else percentage(raw[item['channel']-1])
                self.assertEqual(scene.objects[gauge]['value'],expected)
                self.assertEqual(scene.objects[value]['text'],f'{expected}%')
                self.assertEqual(scene.objects[container]['size'],c.rectangle(item)[2:])
                self.assertEqual(scene.objects[gauge]['flags']&1,1 if item['kind']=='number' else 0)
                if item['kind']=='battery':
                    self.assertEqual(scene.objects[gauge]['styles'][(0x1032,0)],1)
                    self.assertEqual(scene.objects[gauge]['styles'][(0x840,0)],0)
        image=scene.image;base=p.build_patch(self.original)
        changed={i for i in range(len(base)) if image[i]!=base[i]}
        self.assertTrue(changed<=set(range(0x59ae4,0x59ae8))|set(range(0x5850c,0x58510)))
        self.assertTrue(p.inspect_image(image)['recognized']);self.assertEqual(p.revert_patch(image),self.original)
        from test_startup_animation import asset
        wrapped=p.build_patch(self.original,dashboard='custom',layout=z.DEFAULT,startup_animation=asset())
        self.assertTrue(p.inspect_image(wrapped)['recognized']);self.assertEqual(p.revert_patch(wrapped),self.original)
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        import installer
        for raw in (raw_fixture(wrapped),windows_prefix(raw_fixture(wrapped))):
            after,_,_=installer.plan_transfer(raw,self.original,self.original)
            self.assertEqual(installer.recognize_installed(after,self.original),'original-2.0.5')
            after,_,_=installer.plan_transfer(after,wrapped,self.original)
            self.assertEqual(installer.recognize_installed(after,self.original),p.inspect_image(wrapped)['variant'])
    def test_oom_and_cleanup_for_seven_containers_keep_stock_visible(self):
        spec=copy.deepcopy(z.DEFAULT)
        spec['widgets']+=[dict(id='g5',channel=5,kind='number',zone='A',col=3,row=0,color='#ffffff'),
                          dict(id='g6',channel=6,kind='number',zone='B',col=4,row=2,color='#ffffff')]
        for failure in range(1,29):
            scene=self.scene(spec,construct=False);scene.fail_at=failure
            scene.run(scene.constructor,(scene.word(0x200005d8),2),RETURN_VALUE)
            self.assertFalse(scene.objects[scene.word(PANEL)]['children'])
            for pointer in z.UPPER_NATIVE:self.assertFalse(scene.objects[scene.word(pointer)]['flags']&1)
        scene=self.scene(spec);self.assertEqual(len(scene.objects[scene.word(PANEL)]['children']),7)
        scene.allowed_native=[(BASE+0x59b50,BASE+0x59bb4)];scene.run(BASE+0x59b50)
        scene.allowed_native=[];self.assertEqual(scene.run(scene.timer,(0x20007800,)),[])


if __name__=='__main__':unittest.main()
