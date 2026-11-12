"""Whole-home style on 2.0.5; exercise the actual constructor and both data assets offline."""
import copy,io,os,struct,sys,unittest
from pathlib import Path
from unittest import mock
import tkinter as tk
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,dashboard_custom as c,dashboard_wallpaper as wp,dashboard_zones as z,editor,installer
import patch_firmware as p
import test_dashboard_custom as probes
from test_dashboard_custom import HAVE_ARM,BASE,ROOT,PANEL
from test_installer import raw_fixture
from test_installer_switching import windows_prefix
from test_startup_animation import asset

def source():
    img=Image.new('RGB',(240,320),'#113355');img.paste('#cc4422',(0,200,240,320))
    buf=io.BytesIO();img.save(buf,format='PNG');return buf.getvalue()
def design():
    return c.validate_layout({**copy.deepcopy(z.DEFAULT_LOWER),'schema':12,'wallpaper':wp.convert(source())})

class Contract(unittest.TestCase):
    def test_photo_preview_and_portable_json_match_pixels_above_and_below(self):
        spec=design();img=wp.photo(spec['wallpaper'])
        self.assertEqual(img.size,(240,320));self.assertEqual(img.getpixel((20,30)),(17,51,85))
        self.assertEqual(img.getpixel((20,250)),(204,68,34))
        self.assertEqual(c.parse_layout(c.canonical_json(spec)),spec)
        for value in ('','../../foo.jpg','A'*wp.TEXT_BYTES):
            with self.assertRaises(ValueError):c.validate_layout({**spec,'wallpaper':value})
    def test_editor_switches_between_photo_full_color_and_stock_background(self):
        root=tk.Tk();root.withdraw();ui=editor.DashboardEditor(root,layout=z.DEFAULT_LOWER,compact=True)
        try:
            with mock.patch.object(editor.filedialog,'askopenfilename',return_value='test.png'),mock.patch('startup_media.read_source',return_value=('test.png',source())):
                ui.choose_wallpaper()
            spec=ui.get_layout();self.assertEqual(spec,design());self.assertTrue(ui.canvas.find_withtag('wallpaper'))
            ui.apply_theme('Menthe');self.assertEqual(ui.get_layout()['background'],'#132b29')
            self.assertIsNone(ui.get_layout()['wallpaper']);self.assertFalse(ui.canvas.find_withtag('wallpaper'))
            ui.stock_background();self.assertEqual(ui.get_layout()['schema'],6);self.assertNotIn('wallpaper',ui.get_layout())
        finally:ui.destroy();root.destroy()

@unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official firmware and emulator required')
class Radio(unittest.TestCase):
    probe=probes.CustomArmTests.probe
    @classmethod
    def setUpClass(cls):cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
    def test_native_root_draws_full_image_panel_is_clear_and_upper_widgets_remain(self):
        spec=design()
        for photo in (spec['wallpaper'],None):
            q=self.probe({**spec,'wallpaper':photo})
            root=q.objects[q.word(ROOT)];panel=q.objects[q.word(PANEL)]
            self.assertEqual(panel['styles'][(0x21,0)],0)
            self.assertEqual(len(panel['children']),len(spec['widgets']))
            if photo:
                desc=root['styles'][(0x828,0)];self.assertEqual(bytes(q.cpu.mem_read(desc,12)),wp.descriptor())
                self.assertEqual(bytes(q.cpu.mem_read(BASE+wp.DATA_OFFSET,wp.DATA_BYTES)),wp.raw(photo))
            else:self.assertNotIn((0x828,0),root['styles'])
            flags=[args[0] for name,args in q.calls if name=='add_flag' and args[1]==1]
            for slot in (*z.UPPER_NATIVE,0x200005d8):self.assertNotIn(q.word(slot),flags)
    def test_switching_both_usb_modes_with_and_without_startup_and_rejecting_tampering(self):
        spec=design()
        for fast in (False,True):
            for media in (None,asset()):
                built=p.build_patch(self.original,dashboard='custom',usb_1ms=fast,layout=spec,startup_animation=media)
                self.assertEqual(p.inspect_image(built)['layout'],spec)
                self.assertEqual(p.revert_patch(built),self.original)
                for raw in (raw_fixture(built),windows_prefix(raw_fixture(built))):
                    self.assertIn('custom',installer.recognize_installed(raw,self.original))
                corrupt=bytearray(built);corrupt[wp.DATA_OFFSET+wp.PALETTE_BYTES]^=3
                self.assertFalse(p.inspect_image(bytes(corrupt))['recognized'])
