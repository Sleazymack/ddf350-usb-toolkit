"""Exercise the optional battery header on the same native hooks as the wallpaper."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
import dashboard_custom as c,dashboard_header as h,dashboard_wallpaper as wp, dashboard_fullscreen as lcd
import patch_firmware as p, editor
from test_dashboard_wallpaper import design
import test_fullscreen_dashboard as full
from test_dashboard_six import HAVE_ARM,ROOT,PANEL
from test_dashboard_custom import CustomProbe
from unittest.mock import patch

if HAVE_ARM:
    class HeaderProbe(CustomProbe):
        def prepare_home(self):
            root=super().prepare_home();items=self.objects[root]['children']
            menu=self.word(lcd.MENU);items.remove(menu);items.append(menu);self.sync_children(root)
            self.stock=tuple(items);return root

class EditorTests(unittest.TestCase):
    def test_toggle_keeps_wallpaper_and_grid_and_survives_export(self):
        root=tk.Tk();root.withdraw()
        try:
            spec=design();ui=editor.DashboardEditor(root,layout=spec,compact=True)
            self.assertFalse(ui.minimal_header.get());ui.header_check.invoke()
            chosen=ui.get_layout()
            self.assertEqual(chosen,{**spec,'header':'battery_only'})
            ui.set_layout(c.parse_layout(c.canonical_json(chosen)))
            self.assertTrue(ui.canvas.find_withtag('wallpaper'));self.assertEqual(len(ui.canvas.find_withtag('mini_battery')),3)
            ui.header_check.invoke();self.assertEqual(ui.get_layout(),spec)
            self.assertFalse(ui.canvas.find_withtag('mini_battery'))
            with self.assertRaises(ValueError):c.validate_layout({**spec,'header':'other'})
        finally:root.destroy()

@unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official firmware and emulator required')
class NativeTests(unittest.TestCase):
    def probe(self,*args,**kwargs):
        with patch.object(full,'OverlayProbe',HeaderProbe):
            return full.FullscreenTests.probe(self,*args,**kwargs)
    @classmethod
    def setUpClass(cls):cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()

    def test_photo_alignment_menu_input_and_live_battery(self):
        spec={**design(),'header':'battery_only'}
        for fast,photo in ((False,None),(True,spec['wallpaper'])):
            spec2={**spec,'wallpaper':photo}
            img=p.build_patch(self.original,dashboard='custom',layout=spec2,usb_1ms=fast)
            self.assertEqual(p.inspect_image(img)['layout'],spec2);self.assertEqual(p.revert_patch(img),self.original)
            q=self.probe(img,fast);kids=q.objects[q.word(ROOT)]['children'];self.assertEqual(q.stock,tuple(kids[:-1]))
            cover=q.objects[kids[-1]];self.assertEqual(cover['size'],(240,200));self.assertEqual(cover['align'],(1,0,0))
            if photo:self.assertEqual(bytes(q.cpu.mem_read(cover['styles'][0x828,0],12)),wp.descriptor(200))
            else:self.assertNotIn((0x828,0),cover['styles'])
            self.assertFalse(q.objects[q.word(lcd.MENU)]['flags']&1)
            self.assertFalse(cover['flags']&(1|c.NONINTERACTIVE_CLIPPED))
            bar,tip,cache=(q.objects[ch] for ch in cover['children']);self.assertTrue(cache['flags']&1)
            for obj,box in ((bar,h.BODY),(tip,h.TIP)):
                self.assertFalse(obj['flags']&c.NONINTERACTIVE_CLIPPED);self.assertEqual(obj['align'],(1,*box[:2]));self.assertEqual(obj['size'],box[2:])
            self.assertEqual(len(q.objects[q.word(PANEL)]['children']),len(spec2['widgets']))
            q.objects[q.word(0x200005cc)]['value']=63
            def tick():q.run(q.timer,(0x20007800,))
            tick();self.assertEqual(bar['value'],63)
            q.put(lcd.USB_CONFIG_STATE,5);q.cpu.mem_map(lcd.USB_CLOCK_ENABLE&~4095,4096);q.put(lcd.USB_CLOCK_ENABLE,1<<23)
            q.cpu.mem_map(lcd.USB_FRAME_NUMBER&~4095,4096);q.put(lcd.USB_FRAME_NUMBER,1);tick()
            q.put(lcd.USB_FRAME_NUMBER,2);tick();self.assertEqual(bar['value'],100)
            q.put(lcd.USB_CONFIG_STATE,0);tick();self.assertEqual(bar['value'],63)
            # Every allocation in the upper layer may fail; roll back both new trees.
            count=4*len(spec['widgets'])
            for failure in range(count+1,count+5):
                failed=self.probe(img,fast,fail=failure)
                self.assertEqual(tuple(failed.objects[failed.word(ROOT)]['children']),failed.stock)
                self.assertFalse(failed.objects[failed.word(PANEL)]['children'])
