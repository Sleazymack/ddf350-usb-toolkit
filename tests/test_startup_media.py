"""Bounded user media, exact preview and optional wizard integration; no USB."""
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
import startup_media as m
import startup_animation as a
import wizard
import i18n


def image_bytes(format='PNG',color='red',size=(64,96),**kwargs):
    stream=io.BytesIO();Image.new('RGB',size,color).save(stream,format=format,**kwargs);return stream.getvalue()


def gif_bytes(count=4,duration=100):
    frames=[Image.new('RGB',(32,48),(n*5%256,n*17%256,n*31%256)) for n in range(count)]
    stream=io.BytesIO();frames[0].save(stream,format='GIF',save_all=True,append_images=frames[1:],duration=duration,loop=0)
    return stream.getvalue()


class MediaTests(unittest.TestCase):
    def test_photo_has_exact_native_bytes_aspect_and_margins(self):
        for fmt in ('PNG','JPEG','BMP'):
            for size,bounds in (((60,80),(24,32,216,288)),((80,40),(24,112,216,208)),((40,80),(56,32,184,288))):
                media=m.from_bytes(image_bytes(fmt,color='red',size=size))
                self.assertEqual(media.kind,'photo')
                self.assertEqual(len(media.asset),192*256*2)
                frame=m.preview_media(media)[0][0]
                self.assertEqual(frame.size,(240,320));self.assertEqual(frame.getbbox(),bounds)
                self.assertEqual(frame.getpixel((120,160)),(255,0,0))
                self.assertEqual(media.asset[(128*192+96)*2:][:2],b'\xf8\x00')

    def test_photo_exif_transparency_and_input_limits(self):
        exif=Image.Exif();exif[274]=6
        upright=m.from_bytes(image_bytes('JPEG',size=(80,40),exif=exif))
        self.assertEqual(m.preview_media(upright)[0][0].getbbox(),(56,32,184,288))
        out=io.BytesIO();Image.new('RGBA',(24,32),(255,0,0,0)).save(out,format='PNG')
        self.assertIsNone(m.preview_media(m.from_bytes(out.getvalue()))[0][0].getbbox())
        for blob in (image_bytes(size=(4097,1)),b'garbage',image_bytes()[:20]):
            with self.assertRaises(ValueError):m.from_bytes(blob)

    def test_limits_are_per_frame_by_content_and_strict_decimal_bytes(self):
        allowed=gif_bytes(20,200)
        media=m.from_bytes(allowed.ljust(279999,b'\0'),name='a.png')
        self.assertEqual(media.kind,'gif')
        self.assertEqual(media.info['frames'],20)
        self.assertEqual(media.info['duration_ms'],4000)
        self.assertEqual(m.preview_media(media)[1],[200]*20)
        for blob in (allowed.ljust(280000,b'\0'),gif_bytes(3,[200,190,1000]),gif_bytes(21,200),gif_bytes(5,1000),gif_bytes(2,1050)):
            with self.assertRaises(ValueError):m.from_bytes(blob,name='a.png')
        out=io.BytesIO()
        Image.new('RGB',(24,32),'red').save(out,format='PNG',save_all=True,append_images=[Image.new('RGB',(24,32),'blue')])
        with self.assertRaises(ValueError):m.from_bytes(out.getvalue(),name='a.gif')

    def test_self_test(self):self.assertTrue(m.self_test())


class MediaWizardTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.overrideredirect(True);self.root.attributes('-alpha',0)
        self.ui=wizard.Wizard(self.root)
    def tearDown(self):
        if hasattr(self,'old_scale'):self.root.tk.call('tk','scaling',self.old_scale)
        self.ui.busy=False;self.ui.close();i18n.set_language('fr')
    def test_smallest_view_shows_preview_error_and_footer_without_scrolling(self):
        import ui_audit
        self.old_scale=self.root.tk.call('tk','scaling')
        i18n.set_language('fr');self.root.tk.call('tk','scaling',8/3)
        self.root.minsize(400,300);self.root.maxsize(400,300)
        self.root.geometry('400x300');self.root.update()
        blob=image_bytes();name='x'*160+'.png';media=m.from_bytes(blob,name=name)
        self.ui.step=4;self.ui.events.put(('media_ready',(name,blob,media),None));self.ui.poll();self.root.update()
        for error in ('','Erreur de conversion '+('abcdefghijkl '*20)):
            self.ui.status.set(error);self.root.update()
            self.assertEqual(ui_audit.inspect(self.root),[])
            self.assertEqual(self.ui.body_view.canvas.yview(),(0.0,1.0))
            self.assertFalse(self.ui.body_view._bar_visible)
            box=self.ui.preview_canvas.bbox('frame');self.assertGreater(box[3]-box[1],45)
            self.assertTrue(all(w.winfo_ismapped() for w in (self.ui.forward,self.ui.back,self.ui.media_panel.apply)))
            self.assertTrue(self.ui.media_panel.file.cget('text').endswith('…'))

    def test_picker_preview_apply_and_reset(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            self.ui.step=4;self.ui.render();self.root.update()
            self.assertIsNone(self.ui.preview_canvas)
            for blob,kind in ((image_bytes(),'photo'),(gif_bytes(3,250),'gif')):
                path=Path(folder)/'local.media';path.write_bytes(blob)
                with mock.patch.object(wizard.filedialog,'askopenfilename',return_value=str(path)):
                    self.ui.media_panel.choose.invoke()
                    event=self.ui.events.get(timeout=5);self.assertEqual(event[0],'media_ready')
                    self.ui.events.put(event);self.ui.poll();self.root.update()
                self.assertEqual(self.ui.media_candidate.kind,kind)
                self.assertEqual(str(self.ui.forward.cget('state')),'disabled')
                self.assertEqual(len(self.ui.preview_images),1 if kind=='photo' else 3)
                self.assertEqual(self.ui.preview_after is None,kind=='photo')
                self.ui.media_panel.apply.invoke();self.assertEqual(self.ui.startup_media.kind,kind)
                self.ui.media_panel.original.invoke();self.assertIsNone(self.ui.startup_media)
                self.assertIsNone(self.ui.preview_canvas)

    def test_failed_import_preserves_applied_photo(self):
        self.ui.step=4;self.ui.startup_media=m.from_bytes(image_bytes());self.ui.render()
        self.ui.events.put(('media_error',m.GIF_TIMING,None));self.ui.poll()
        self.assertEqual(self.ui.startup_media.kind,'photo');self.assertTrue(self.ui.status.get())


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'official input not supplied')
class FirmwareTests(unittest.TestCase):
    def test_legacy_gif_to_photo_then_limited_gif_then_original(self):
        import patch_firmware as p, installer, startup_photo as ph
        from test_installer import raw_fixture
        from test_startup_animation import loop_asset
        from test_installer_switching import windows_prefix
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        legacy=p.build_patch(original,startup_animation=loop_asset())
        pixels=m.from_bytes(image_bytes()).asset
        still=p.build_patch(original,usb_1ms=True,dashboard='strip_drift',startup_photo=pixels)
        gif=p.build_patch(original,startup_animation=m.from_bytes(gif_bytes(3,250)).asset)
        with self.assertRaises(ValueError):installer.validate_new_target(legacy)
        for target in (still,gif,original):installer.validate_new_target(target)
        self.assertEqual(p.revert_patch(still),original)
        self.assertEqual(ph.unpack(still)[1],pixels)
        desc=struct.unpack_from('<III',still,ph.DESCRIPTOR)
        self.assertEqual(desc,(4|192<<10|256<<21,192*256*2,p.FLASH_BASE+ph.DATA))
        for off in (0x10afe,ph.SLOT,ph.CODE,ph.DESCRIPTOR,ph.DATA):
            bad=bytearray(still);bad[off]^=1
            self.assertFalse(p.inspect_image(bytes(bad))['recognized'])
        raw=raw_fixture(legacy)
        for target in (still,gif,still,original):
            raw,_,_=installer.plan_transfer(windows_prefix(raw),target,original)
            self.assertEqual(installer.recognize_installed(raw,original),p.inspect_image(target)['variant'])

from test_startup_animation import HAVE_ARM
@unittest.skipUnless(HAVE_ARM,'optional CPU emulator unavailable')
class PhotoCpuTests(unittest.TestCase):
    def test_photo_belongs_to_stock_welcome_not_persistent_overlay(self):
        import test_startup_animation as em, startup_photo as ph, dashboard_custom as gui
        support={gui.API[key]-gui.BASE:key for key in ('obj_create','remove_style_all','clear_flag','size','align','style','bg_color')}
        for mode,root,success in ((1,0x2000c000,True),(2,0x2000c000,True),(1,0,True),(1,0x2000c000,False)):
            probe=em.Probe()
            probe.u.mem_write(gui.BASE+ph.CODE,ph.constructor())
            probe.u.mem_write(0x200005b0,bytes([mode]));probe.write(0x200005ac,root)
            with mock.patch.dict(em.APIS,support),mock.patch.object(probe,'allocate',wraps=probe.allocate):
                # Model obj_create's return for this single native child; any
                # unmodelled native call fails the instruction/return checks.
                def api(u,addr,size,user):
                    if addr!=gui.API['obj_create']:return
                    probe.calls.append(('parent',u.reg_read(em.REGS[0])))
                    u.reg_write(em.REGS[0],0x2000d000 if success else 0)
                    u.reg_write(em.UC_ARM_REG_PC,u.reg_read(em.UC_ARM_REG_LR))
                # The original hook must not also intercept this one API.
                del em.APIS[gui.API['obj_create']-gui.BASE]
                probe.u.hook_add(em.UC_HOOK_CODE,api)
                self.assertEqual(probe.run(gui.BASE+ph.CODE),0x13572468)
            names=[item[0] for item in probe.calls]
            self.assertEqual(names[0],'native_start')
            if mode==1 and root:
                self.assertIn(('parent',root),probe.calls)
                if success:
                    self.assertIn(('style',[0x2000d000,0x828,gui.BASE+ph.DESCRIPTOR,0]),probe.calls)
                else:self.assertNotIn('style',names)
            else:self.assertEqual(names,['native_start'])
            self.assertFalse(set(names)&{'timer','decoder','alloc','screen'})


if __name__=='__main__':unittest.main()
