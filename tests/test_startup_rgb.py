"""Prepared colorful GIFs: native pixels, bounded Thumb decoder and replacement."""
import hashlib
import io
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
import startup_media as media
import startup_animation as animation
import startup_player_rgb as player
from test_startup_animation import HAVE_ARM


def colorful_gif():
    frames=[]
    for offset in (0,1):
        frame=Image.new('P',(128,160))
        frame.putpalette([value for n in range(256) for value in (n,(n*7+offset)%256,(n*17)%256)])
        frame.putdata([(x+y*128)%256 for y in range(160) for x in range(128)])
        frames.append(frame)
    stream=io.BytesIO()
    frames[0].save(stream,format='GIF',save_all=True,append_images=frames[1:],duration=[200,400],optimize=False)
    return stream.getvalue()


class FormatTests(unittest.TestCase):
    def test_all_source_colors_survive_native_encoding_without_palette_reduction(self):
        source=colorful_gif()
        with mock.patch.object(Image.Image,'resize',side_effect=AssertionError('No resize')),\
             mock.patch.object(Image.Image,'quantize',side_effect=AssertionError('No quantization')):
            result=media.from_bytes(source)
        decoded=animation.decode_asset(result.asset)
        self.assertEqual(animation.version_for(result.asset),4)
        self.assertEqual(decoded['durations'],[200,400])
        with Image.open(io.BytesIO(source)) as image:
            for i,pixels in enumerate(decoded['frames']):
                image.seek(i);rgb=image.convert('RGB').tobytes()
                expected=b''.join(struct.pack('<H',(r>>3)<<11|(g>>2)<<5|b>>3) for r,g,b in zip(rgb[::3],rgb[1::3],rgb[2::3]))
                self.assertEqual(pixels,expected)
        self.assertGreater(len(set(struct.iter_unpack('<H',decoded['frames'][0]))),16)
        for offset,value in ((0,b'BAD!'),(14,b'\x10\0'),(16,b'\xff'*4),(20,b'\1')):
            bad=bytearray(result.asset);bad[offset:offset+len(value)]=value
            with self.assertRaises(ValueError):animation.decode_asset(bytes(bad))

    def test_compiled_player_matches_its_sources(self):
        root=Path(__file__).resolve().parents[1]/'startup'
        self.assertEqual(hashlib.sha256((root/'player-rgb.c').read_bytes()).hexdigest(),player.DATA['c_sha256'])
        self.assertEqual(hashlib.sha256((root/'player.ld').read_bytes()).hexdigest(),player.DATA['linker_sha256'])
        self.assertEqual(hashlib.sha256(player.CODE).hexdigest(),player.DATA['sha256'])


@unittest.skipUnless(HAVE_ARM,'optional CPU emulator unavailable')
class CpuTests(unittest.TestCase):
    def test_largest_frame_native_lines_and_cleanup(self):
        from test_startup_animation import Probe
        result=media.from_bytes(colorful_gif());decoded=animation.decode_asset(result.asset)
        probe=Probe(result.asset);self.assertEqual(probe.start(),0x13572468)
        pixels=probe.field('pixels')
        self.assertEqual(probe.allocs[pixels][0],40960)
        for x,y,length in ((-1,0,12),(0,-1,12),(0,275,12),(230,0,11),(0,0,-1)):
            self.assertEqual(probe.line(x,y,length)[0],0)
        for index in range(2):
            self.assertEqual(bytes(probe.u.mem_read(pixels,40960)),decoded['frames'][index])
            for x,y,length in ((0,0,240),(19,137,120),(0,274,240)):
                ok,data=probe.line(x,y,length);self.assertEqual(ok,1)
                expected=b''.join(decoded['frames'][index][2*((y*160//275)*128+(x+n)*128//240):][:2][::-1] for n in range(length))
                self.assertEqual(data,expected)
            probe.tick()
        self.assertEqual(probe.field('active'),0)
        self.assertEqual(probe.field('pixels'),0)
        self.assertFalse(probe.objects);self.assertFalse(probe.timers)
        self.assertEqual(probe.freed.count(pixels),1)

    def test_failures_preserve_native_boot_and_release_frame(self):
        from test_startup_animation import Probe
        blob=media.from_bytes(colorful_gif()).asset
        for failure in [('alloc',1),('alloc',2),('alloc',3),('object',1),('object',2),('event',1),('decoder',1),('timer',1),('screen',1)]:
            with self.subTest(failure=failure):
                probe=Probe(blob,fail=failure);self.assertEqual(probe.start(),0x13572468)
                self.assertFalse(probe.objects);self.assertFalse(probe.timers)
                self.assertFalse(any(size==40960 for size,kind in probe.allocs.values()))
        for offset,value in ((0,b'BAD!'),(14,b'\x10\0'),(16,b'\xff'*4),(54,b'\xff'*4)):
            bad=bytearray(blob);bad[offset:offset+len(value)]=value
            probe=Probe(bytes(bad));self.assertEqual(probe.start(),0x13572468)
            self.assertFalse(probe.objects);self.assertFalse(probe.timers)


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'official input not supplied')
class FirmwareTests(unittest.TestCase):
    def test_new_player_recognition_revert_and_switching_with_and_without_wallpaper(self):
        import patch_firmware as patch,installer
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        from editor import DEFAULT_LAYOUT
        from test_startup_animation import asset
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        animation_asset=media.from_bytes(colorful_gif()).asset
        layouts=[None,None]
        # Exercise the actual photo-backed extended placement, as well as the
        # normal appendix. The native player must not overlap dashboard data.
        import dashboard_gauges as gauges
        import dashboard_wallpaper as wallpaper
        from PIL import Image
        layouts[1]=gauges.upgrade(DEFAULT_LAYOUT)
        layouts[1]['full_background']=True
        stream=io.BytesIO();Image.new('RGB',(240,320),'navy').save(stream,format='PNG')
        layouts[1]['wallpaper']=wallpaper.convert(stream.getvalue())
        for layout in layouts:
            kwargs={'dashboard':'original'} if layout is None else {'dashboard':'custom','layout':layout}
            target=patch.build_patch(original,usb_1ms=True,startup_animation=animation_asset,**kwargs)
            self.assertEqual(patch.inspect_image(target)['startup_player_version'],4)
            self.assertEqual(patch.revert_patch(target),original)
            installer.validate_new_target(target)
            for offset in (0x10afe,animation.PLAYER_OFFSET+20,len(target)-42):
                bad=bytearray(target);bad[offset]^=1
                self.assertFalse(patch.inspect_image(bytes(bad))['recognized'])
            raw=windows_prefix(raw_fixture(target))
            for old in (patch.build_patch(original,startup_animation=asset()),original,target):
                raw,_,_=installer.plan_transfer(raw,old,original)
                self.assertEqual(installer.recognize_installed(raw,original),patch.inspect_image(old)['variant'])


if __name__=='__main__':unittest.main()
