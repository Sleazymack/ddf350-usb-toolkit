"""Offline ARM player checks: modeled GUI/allocator, actual generated Thumb.

These tests do not establish LCD appearance, scheduler timing or RF stability.
No USB access. Assets are synthetic; the user's chosen GIF stays outside source.
"""
import hashlib
import os
from pathlib import Path
import random
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import startup_animation as anim
import startup_player_blob as player
import startup_player_v1 as player_v1
import patch_firmware as p

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
    from unicorn.arm_const import *
    HAVE_ARM=True
except ImportError:HAVE_ARM=False


def asset(frames=4,duration=100):
    palette=struct.pack('<16H',*[n*4097 for n in range(16)])
    blob=bytearray(struct.pack('<8sHHHHI',b'DDFANM1\0',16,16,frames,16,128)+palette)
    for frame in range(frames):
        pixels=bytes(((i+frame)%256 for i in range(128)))
        delta=struct.pack('<HH',0,128)+pixels+struct.pack('<HH',65535,0)
        blob+=struct.pack('<HI',duration,len(delta))+delta
    return bytes(blob)


def loop_asset():
    """Sparse first frame leaves the previous cycle's last pixel to be cleared."""
    from startup.convert_gif import encode_delta
    source=asset(10,50)
    blob=bytearray(anim.LOOP_MAGIC+source[8:52])
    previous=bytes(128)
    for i in range(10):
        pixels=bytearray(128);pixels[i]=i+1
        delta=encode_delta(previous,bytes(pixels))
        blob+=struct.pack('<HI',50,len(delta))+delta
        previous=bytes(pixels)
    return bytes(blob)


class AssetTests(unittest.TestCase):
    def test_loop_format_rejects_wrong_frame_count_and_duration(self):
        for at,value in ((12,9),(52,100)):
            blob=bytearray(loop_asset());struct.pack_into('<H',blob,at,value)
            with self.assertRaises(ValueError):anim.decode_asset(bytes(blob))

    def test_animation_cli_option_is_retired(self):
        from test_patch_firmware import cli
        result=cli('patch','nonexistent.bin','--startup-animation','retired.ddfa','--dry-run')
        self.assertEqual(result.returncode,2)
        self.assertIn('unrecognized arguments',result.stderr)

    def test_strict_bounds_and_roundtrip(self):
        good=asset(40);decoded=anim.decode_asset(good)
        self.assertEqual(len(decoded['frames']),40)
        for n,frame in enumerate(decoded['frames']):self.assertEqual(frame,bytes((i+n)%256 for i in range(128)))
        bad=[good[:-1],good+b'junk',good[:8]+b'\xff'*12+good[20:]]
        for at in (0,8,10,12,14,16,52,54,58,60):
            altered=bytearray(good);altered[at:at+2]=b'\xff\xff';bad.append(bytes(altered))
        for candidate in bad:
            with self.assertRaises(ValueError):anim.decode_asset(candidate)

    def test_blob_matches_own_sources(self):
        root=Path(__file__).resolve().parents[1]/'startup'
        self.assertEqual(hashlib.sha256((root/'player.c').read_bytes()).hexdigest(),player.DATA['c_sha256'])
        self.assertEqual(hashlib.sha256((root/'player.ld').read_bytes()).hexdigest(),player.DATA['linker_sha256'])
        self.assertEqual(hashlib.sha256(player.CODE).hexdigest(),player.DATA['sha256'])


if HAVE_ARM:
    REGS=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3]
    SAVED=[UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11]
    STOP,STACK=0x10000000,0x2001f000
    APIS={0x5b2d0:'native_start',0x10464:'native_end',0x4a9b8:'alloc',0x4ab54:'free',
          0x4bf0c:'create',0x4bffc:'init',0x4c21c:'delete',0x50244:'size',0x501f2:'pos',
          0x50500:'bg',0x5058a:'opa',0x500c4:'style',0x4b5b0:'event',0x46554:'userdata',
          0x4881c:'src',0x4ed80:'invalidate',0x480ec:'decoder',0x5136c:'screen',0x42be0:'screen',
          0x53c98:'timer',0x53cdc:'timer_delete',0x2fb16:'head',0x2fb46:'next'}

    class Probe:
        def __init__(self,blob=None,fail=None,original=None,*,version=None):
            self.blob=blob or asset(40);self.fail=fail;self.calls=[];self.allocs={};self.counter={};self.heap=0x2000d000
            self.objects={};self.events={};self.decoders=[];self.timers={};self.freed=[];self.context=None;self.native_end=None
            self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS);self.u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M3)
            self.u.mem_map(p.FLASH_BASE,0x100000);self.u.mem_map(0x20000000,0x20000);self.u.mem_map(STOP,0x1000)
            if original:self.u.mem_write(p.FLASH_BASE,original)
            self.player=anim.PLAYERS[version or anim.version_for(self.blob)]
            code=bytearray(self.player.CODE);self.asset_address=anim.PLAYER_BASE+len(code)
            struct.pack_into('<II',code,4,self.asset_address,len(self.blob))
            self.u.mem_write(anim.PLAYER_BASE,bytes(code)+self.blob)
            self.u.mem_write(0x200005b0,b'\x01');self.write(0x200005ac,0x2000c000)
            self.u.hook_add(UC_HOOK_CODE,self.hook)
        def write(self,address,*values):self.u.mem_write(address,struct.pack('<'+'I'*len(values),*(v&0xffffffff for v in values)))
        def read(self,address):return struct.unpack('<I',self.u.mem_read(address,4))[0]
        def symbol(self,name):return self.player.DATA['symbols'][name]['address']
        def field(self,name):return self.read(self.context+self.player.DATA['context_offsets'][name])
        def allocate(self,size,kind):
            self.counter[kind]=self.counter.get(kind,0)+1
            if self.fail==(kind,self.counter[kind]):return 0
            address=self.heap;self.heap+=(size+15)//16*16+16
            if self.heap>=0x2001a000:raise AssertionError('model heap exhausted')
            self.allocs[address]=(size,kind);self.u.mem_write(address,bytes(size));return address
        def hook(self,u,address,size,user):
            if address==STOP:u.emu_stop();return
            name=APIS.get(address-p.FLASH_BASE)
            if name is None:return
            args=[u.reg_read(r) for r in REGS];self.calls.append((name,args));result=0
            if name=='native_start':result=0x13572468
            elif name=='native_end':self.native_end=(args,[u.reg_read(r) for r in SAVED],u.reg_read(UC_ARM_REG_SP))
            elif name=='alloc':
                result=self.allocate(args[0],'alloc')
                if result and args[0]==self.player.DATA['context_size']:self.context=result
            elif name=='free':
                if args[0] not in self.allocs:raise AssertionError('double/foreign free')
                del self.allocs[args[0]];self.freed.append(args[0])
            elif name=='create':
                result=self.allocate(64,'object')
                if result:self.objects[result]=(args[0],args[1])
            elif name=='delete':
                if args[0] not in self.objects:raise AssertionError('foreign/double GUI deletion')
                def delete(obj):
                    for child,(_type,parent) in list(self.objects.items()):
                        if parent==obj:delete(child)
                    if obj in self.events:
                        callback,ctx=self.events.pop(obj);event=0x2000c100;self.write(event+16,ctx)
                        # Native callback is a simple flag write, checked separately.
                        self.write(ctx+self.player.DATA['context_offsets']['dead'],1)
                    del self.objects[obj];del self.allocs[obj]
                delete(args[0])
            elif name=='event':
                result=self.allocate(16,'event')
                if result:self.events[args[0]]=(args[1],args[3])
            elif name=='userdata':result=self.read(args[0]+16)
            elif name=='screen':result=0 if self.fail==('screen',1) else 0x2000c000
            elif name=='decoder':
                result=self.allocate(20,'decoder')
                if result:self.decoders.insert(0,result)
            elif name=='timer':
                result=self.allocate(24,'timer')
                if result:self.write(result,args[1],0,args[0],args[2],0xffffffff,0);self.timers[result]=args[0]
            elif name=='timer_delete':
                if args[0] not in self.timers:raise AssertionError('foreign/double timer deletion')
                del self.timers[args[0]];del self.allocs[args[0]]
            elif name=='head':result=self.decoders[0] if self.decoders else 0
            elif name=='next':
                i=self.decoders.index(args[1]);result=self.decoders[i+1] if i+1<len(self.decoders) else 0
            for r in REGS+[UC_ARM_REG_R12]:u.reg_write(r,0xc1c1c1c1)
            u.reg_write(UC_ARM_REG_R0,result);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
        def run(self,address,*args):
            self.u.reg_write(UC_ARM_REG_SP,STACK);self.u.reg_write(UC_ARM_REG_LR,STOP|1)
            for i,r in enumerate(REGS):self.u.reg_write(r,args[i] if i<len(args) else 0xabcdef00+i)
            for i,r in enumerate(SAVED):self.u.reg_write(r,0x34343400+i)
            if len(args)>4:self.write(STACK,*args[4:])
            self.u.emu_start(address|1,STOP,count=2000000)
            if self.u.reg_read(UC_ARM_REG_PC)!=STOP:raise AssertionError('instruction budget exhausted')
            if self.u.reg_read(UC_ARM_REG_SP)!=STACK:raise AssertionError('stack changed')
            if [self.u.reg_read(r) for r in SAVED]!=[0x34343400+i for i in range(8)]:raise AssertionError('callee-saved register changed')
            return self.u.reg_read(UC_ARM_REG_R0)
        def start(self):return self.run(self.symbol('boot_start'))
        def tick(self):
            timer=next(iter(self.timers));self.run(self.timers[timer],timer)
        def line(self,x,y,length):
            session=0x2000c200;output=0x2000c400;self.u.mem_write(output,b'\xcc'*512)
            self.write(session+4,self.context+self.player.DATA['context_offsets']['descriptor'])
            decoder=self.field('decoder');result=self.run(self.read(decoder+8),decoder,session,x,y,length,output)
            data=bytes(self.u.mem_read(output,max(0,length*2) if length<=240 else 512))
            return result,data


@unittest.skipUnless(HAVE_ARM,'optional Unicorn not available')
class PlayerTests(unittest.TestCase):
    def test_full_animation_pixels_and_lifetime(self):
        probe=Probe();self.assertEqual(probe.start(),0x13572468)
        decoded=anim.decode_asset(probe.blob);self.assertEqual(probe.field('active'),1)
        pixels=probe.field('pixels')
        for frame in range(40):
            self.assertEqual(probe.field('frame'),frame+1)
            self.assertEqual(bytes(probe.u.mem_read(pixels,128)),decoded['frames'][frame])
            for x,y,length in ((0,0,240),(21,137,91),(0,274,240)):
                ok,data=probe.line(x,y,length);self.assertEqual(ok,1)
                expected=bytearray()
                for n in range(length):
                    pixel=(y*16//275)*16+(x+n)*16//240
                    pair=decoded['frames'][frame][pixel//2];index=pair&15 if pixel%2 else pair>>4
                    expected+=decoded['palette'][index*2:index*2+2][::-1]
                self.assertEqual(data,bytes(expected))
            probe.tick()
        self.assertEqual(probe.field('active'),0);self.assertEqual(probe.field('pixels'),0)
        self.assertFalse(probe.objects);self.assertFalse(probe.timers);self.assertIn(pixels,probe.freed)
        self.assertEqual(probe.line(0,0,12)[0],0)
        probe.run(probe.symbol('boot_stop_all')) # repeated cleanup is harmless

    def test_loop_draws_every_pose_eight_times_then_cleans_up(self):
        probe=Probe(loop_asset())
        self.assertEqual(probe.start(),0x13572468)
        decoded=anim.decode_asset(probe.blob)
        pixels=probe.field('pixels')
        timer=probe.field('timer')
        allocated=dict(probe.counter)
        for shown in range(80):
            self.assertEqual(probe.field('frame'),shown%10+1)
            self.assertEqual(probe.field('active'),1)
            self.assertEqual(probe.read(timer),50)
            self.assertEqual(bytes(probe.u.mem_read(pixels,128)),decoded['frames'][shown%10])
            self.assertEqual(probe.counter,allocated)
            probe.tick()
        self.assertEqual(probe.field('active'),0)
        self.assertEqual(probe.field('pixels'),0)
        self.assertFalse(probe.timers);self.assertFalse(probe.objects)
        self.assertEqual(probe.freed.count(pixels),1)

    def test_bounds_invalid_asset_and_alternate_boot_fallback(self):
        for offset,value in ((0,b'BAD!'),(8,b'\xff\xff'),(54,b'\xff'*4),(60,b'\xff\xff')):
            bad=bytearray(asset());bad[offset:offset+len(value)]=value
            probe=Probe(bytes(bad));self.assertEqual(probe.start(),0x13572468)
            self.assertFalse(probe.objects);self.assertFalse(probe.timers)
        probe=Probe();probe.u.mem_write(0x200005b0,b'\0');probe.start();self.assertIsNone(probe.context)
        probe=Probe();probe.start()
        for x,y,length in ((-1,0,12),(0,-1,12),(0,275,12),(230,0,11),(0,0,-1)):
            self.assertEqual(probe.line(x,y,length)[0],0)

    def test_oom_fallback_at_every_owned_allocation(self):
        for failure in [('alloc',1),('alloc',2),('alloc',3),('object',1),('object',2),('event',1),('decoder',1),('timer',1),('screen',1)]:
            with self.subTest(failure=failure):
                probe=Probe(fail=failure);self.assertEqual(probe.start(),0x13572468)
                self.assertFalse(probe.objects);self.assertFalse(probe.timers)
                self.assertFalse(any(size==128 for size,kind in probe.allocs.values()))

    def test_native_stage_cleanup_preserves_arguments_and_deleted_root(self):
        probe=Probe();probe.start();probe.run(probe.symbol('boot_cleanup_hook'),11,22,33,44)
        self.assertEqual(probe.native_end,([11,22,33,44],[0x34343400+i for i in range(8)],STACK))
        self.assertEqual(probe.field('active'),0);self.assertFalse(probe.timers)
        probe=Probe();probe.start();root=probe.field('root');callback,ctx=probe.events[root]
        probe.write(0x2000c100+16,ctx);probe.run(callback,0x2000c100)
        self.assertEqual(probe.field('dead'),1)
        # Model the native external parent-tree destruction, then its next tick.
        probe.objects.clear();probe.tick()
        self.assertFalse(probe.timers);self.assertEqual(probe.field('pixels'),0)


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'exact local firmware not supplied')
class WrapperTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_ARM,'optional Unicorn not available')
    def test_top_layer_getter_and_full_clip_survive_native_startup_end(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();p._require_original(original)
        probe=Probe(original=original)
        default=struct.unpack_from('<I',original,0x42b68)[0]
        display=0x2000c000;probe.write(default,display)
        probe.write(display+16,0x2000c040,0x2000c060,0,0x2000c080,0x2000c0a0)
        saved=APIS.pop(0x42be0)
        try:
            self.assertEqual(probe.run(p.FLASH_BASE+0x42be0,display),0x2000c080)
            self.assertEqual(probe.run(p.FLASH_BASE+0x42be0,0),0x2000c080)
            self.assertEqual(probe.run(p.FLASH_BASE+0x42c18,display),0x2000c040)
        finally:APIS[0x42be0]=saved
        probe.start()
        for _ in range(15):probe.tick()
        probe.run(p.FLASH_BASE+0x10464,11,22,33,44)
        self.assertEqual(probe.field('active'),1)
        for _ in range(25):probe.tick()
        self.assertEqual(probe.field('active'),0)
        wrapped=p.build_patch(original,startup_animation=asset())
        self.assertEqual(wrapped[0x10c8a:0x10c8e],original[0x10c8a:0x10c8e])

    def test_previously_shipped_player_remains_recognized_and_switchable(self):
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        import installer
        from dashboard_zones import DEFAULT
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        old=p.build_patch(original,usb_1ms=True,dashboard='custom',layout=DEFAULT,startup_animation=asset(),startup_player_version=1)
        # Independently regenerated using the archived 0.6.0 source ZIP.
        self.assertEqual(hashlib.sha256(old).hexdigest(),'3aa2a6befc77ac57933d28bc982f686e663b8cfaaf5abece05c44438b2a7df17')
        new=p.build_patch(original,usb_1ms=True,dashboard='custom',layout=DEFAULT,startup_animation=asset())
        self.assertEqual(p.inspect_image(old)['startup_player_version'],1)
        self.assertEqual(p.inspect_image(new)['startup_player_version'],2)
        for raw in (raw_fixture(old),windows_prefix(raw_fixture(old))):
            after,_,_=installer.plan_transfer(raw,new,original)
            self.assertEqual(after[installer.APP:installer.APP+len(new)],new)
            self.assertEqual(installer.recognize_installed(after,original),p.inspect_image(new)['variant'])
            after,_,_=installer.plan_transfer(after,old,original)
            self.assertEqual(after[installer.APP:installer.APP+len(old)],old)
        root=Path(__file__).resolve().parents[1]/'startup'
        self.assertEqual(hashlib.sha256((root/'player-v1.c').read_bytes()).hexdigest(),player_v1.DATA['c_sha256'])
        self.assertEqual(hashlib.sha256((root/'player-v1.ld').read_bytes()).hexdigest(),player_v1.DATA['linker_sha256'])

    def test_loop_variant_can_switch_back_to_original_or_an_older_player(self):
        import installer
        from test_installer import raw_fixture
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        for fast in (False,True):
            target=p.build_patch(original,usb_1ms=fast,startup_animation=loop_asset())
            info=p.inspect_image(target)
            self.assertTrue(info['recognized'])
            self.assertEqual(info['startup_player_version'],3)
            self.assertEqual(info['startup_animation']['duration_ms'],4000)
            self.assertEqual(p.revert_patch(target),original)
            raw=raw_fixture(target)
            for previous in (1,2):
                old=p.build_patch(original,startup_animation=asset(),startup_player_version=previous)
                after,_,_=installer.plan_transfer(raw,old,original)
                self.assertEqual(after[installer.APP:installer.APP+len(old)],old)
                back,_,_=installer.plan_transfer(after,target,original)
                self.assertEqual(back[installer.APP:installer.APP+len(target)],target)
            with self.assertRaises(ValueError):p.build_patch(original,startup_animation=loop_asset(),startup_player_version=2)

    def test_complete_regeneration_and_roundtrip(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();base=p.build_patch(original)
        wrapped=anim.attach(base,asset());restored,media=anim.unpack(wrapped)
        self.assertEqual(restored,base);self.assertEqual(media,asset());self.assertEqual(anim.attach(restored,media),wrapped)
        self.assertLessEqual(len(wrapped),983040)

    def test_all_variants_full_regeneration_exact_revert_and_mutation_rejection(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        from editor import DEFAULT_LAYOUT
        for dashboard in ('original','ch1234','ch123456','custom'):
            for fast in (False,True):
                options={'dashboard':dashboard,'usb_1ms':fast}
                if dashboard=='custom':options['layout']=DEFAULT_LAYOUT
                base=p.build_patch(original,**options)
                wrapped=p.build_patch(original,**options,startup_animation=asset())
                info=p.inspect_image(wrapped)
                self.assertTrue(info['recognized']);self.assertEqual(info['dashboard'],dashboard)
                self.assertTrue(info['startup_verified_by_complete_regeneration'])
                self.assertEqual(p.revert_patch(wrapped),original);self.assertEqual(len(wrapped)%4,0)
                self.assertEqual(anim.unpack(wrapped)[0],base)
                for offset in (0,0x10afe,0x10c8a,len(base)+8,anim.PLAYER_OFFSET,anim.PLAYER_OFFSET+8,anim.PLAYER_OFFSET+len(player.CODE)-1,len(wrapped)-40):
                    bad=bytearray(wrapped);bad[offset]^=1
                    self.assertFalse(p.inspect_image(bytes(bad))['recognized'],hex(offset))
                    with self.assertRaises(ValueError):p.revert_patch(bytes(bad))

    def test_switching_to_and_from_animation_and_exact_windows_prefix_exception(self):
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        import installer
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        from editor import DEFAULT_LAYOUT
        images=[p.build_patch(original,dashboard='custom',layout=DEFAULT_LAYOUT,startup_animation=asset()),
                p.build_patch(original,dashboard='ch1234',usb_1ms=True,startup_animation=asset(2)),
                p.build_patch(original,dashboard='ch123456'),original]
        current=raw_fixture(original)
        for image in images+images[::-1]:
            for prefix in (False,True):
                before=windows_prefix(current) if prefix else current
                after,offsets,state=installer.plan_transfer(before,image,original)
                self.assertEqual(after[installer.APP:installer.APP+len(image)],image)
                self.assertEqual(installer.recognize_installed(after,original),p.inspect_image(image)['variant'])
                self.assertEqual(after[:installer.APP],before[:installer.APP])
                self.assertEqual(after[installer.APP+len(image):],before[installer.APP+len(image):])
            current=after
        wrapped=bytearray(raw_fixture(images[0]));wrapped[installer.APP+anim.PLAYER_OFFSET+16]^=1
        with self.assertRaises(ValueError):installer.plan_transfer(wrapped,original,original)

    @unittest.skipUnless(HAVE_ARM,'optional Unicorn not available')
    def test_native_decoder_entrypoints_accept_original_player_abi(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();p._require_original(original)
        probe=Probe(original=original);probe.start()
        descriptor=probe.context+player.DATA['context_offsets']['descriptor'];header=0x2000c100;session=0x2000c200
        self.assertEqual(probe.run(p.FLASH_BASE+0x4810c,descriptor,header),1)
        self.assertEqual(probe.read(header),4|(240<<10)|(275<<21))
        self.assertEqual(probe.run(p.FLASH_BASE+0x48178,session,descriptor,0,0),1)
        self.assertEqual(probe.read(session),probe.field('decoder'))
        self.assertEqual(probe.read(session+36),probe.context)
        self.assertEqual(probe.read(session+20)&31,4,'Decoded output must be RGB565, not the encoded RAW source format')
        self.assertEqual(probe.run(p.FLASH_BASE+0x48264,session,0,274,240,0x2000c400),1)
        probe.run(probe.symbol('boot_stop_all'))
        self.assertEqual(probe.run(p.FLASH_BASE+0x48264,session,0,0,240,0x2000c400),0)

    @unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_STARTUP_ASSET'),'local user media not supplied')
    def test_selected_local_media_all_frames(self):
        blob=Path(os.environ['DDF350_STARTUP_ASSET']).read_bytes();decoded=anim.decode_asset(blob)
        probe=Probe(blob);probe.start();pixels=probe.field('pixels')
        for n,expected in enumerate(decoded['frames']*decoded['repeat_count']):
            self.assertEqual(probe.field('frame'),n%len(decoded['frames'])+1)
            self.assertEqual(bytes(probe.u.mem_read(pixels,len(expected))),expected)
            self.assertEqual(probe.line(0,274,240)[0],1)
            probe.tick()
        self.assertEqual(probe.field('active'),0)


if __name__=='__main__':unittest.main()
