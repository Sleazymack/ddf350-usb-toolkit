"""Exercise the generated face code and verify the exact pixel sources it selects."""
import os,struct,unittest,hashlib,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard_faces as f
import dashboard_themes as t
import patch_firmware as p
from test_dashboard_zones import HAVE_ARM,BASE,PANEL,RETURN_VALUE
from test_dashboard_six import RAM
if HAVE_ARM:
    from test_dashboard_themes import ThemeProbe
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
    from unicorn.arm_const import UC_ARM_REG_SP
    class FacesProbe(ThemeProbe):
        def __init__(self,*args):
            super().__init__(*args);self.api_names[t.IMG_CREATE-BASE]='img_create'
        def allocate(self,kind,parent):
            addr=super().allocate(kind,parent)
            if parent and kind=='obj' and parent==self.word(PANEL):
                self.put(self.word(addr+8),RAM+0x5300)
            return addr
        def on_code(self,cpu,address,size,unused):
            if address!=t.IMG_SRC:return super().on_code(cpu,address,size,unused)
            objaddr,descriptor=[cpu.reg_read(r) for r in self.argument_regs[:2]]
            self.test.assertEqual(cpu.reg_read(UC_ARM_REG_SP)%8,0)
            self.test.assertTrue(self.new_start<=descriptor<=BASE+len(self.image)-12)
            header,n,ptr=struct.unpack('<III',cpu.mem_read(descriptor,12))
            w,h=header>>10&2047,header>>21
            bits={7:1,8:2,9:4}[header&31];self.test.assertEqual(n,4*(1<<bits)+(w*bits+7)//8*h)
            self.test.assertTrue(self.new_start<=ptr<=BASE+len(self.image)-n)
            obj=self.objects[objaddr];self.test.assertEqual(obj['kind'],'img');self.test.assertTrue(obj['alive'])
            obj['asset']=(w,h,bits,bytes(cpu.mem_read(ptr,n)));self.calls.append(('image_source',(objaddr,descriptor)))
            self.return_api(0)

@unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local ARM and 2.0.5 required')
class FacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
    def prepare(self,key,fail=None):
        image=p.build_patch(self.original,dashboard="custom",layout=f.layout(key),usb_1ms=True)
        cpu=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);cpu.detail=True
        ctor=next(cpu.disasm(image[0x59ae4:0x59ae8],BASE+0x59ae4)).operands[0].imm
        q=FacesProbe(self,image,p.FAST_SIZE);q.timer=struct.unpack_from('<I',image,0x5850c)[0]
        q.fail_at=fail;q.run(ctor,(q.word(0x200005d8),2),RETURN_VALUE);return q
    def test_live_firmware_sources_match_artwork_at_stops_and_neutral(self):
        for key in f.THEMES:
            q=self.prepare(key);root=q.objects[q.word(PANEL)]['children'][0];children=q.objects[root]['children']
            leaves=f.scene(key);self.assertEqual(len(children),len(leaves))
            for raw in (-2100,-1300,-20,0,700,1000,2020,-6):
                q.cpu.mem_write(RAM+0x204,struct.pack('<4i',raw,raw,raw,raw))
                q.objects[q.word(0x200005cc)]['value']=75
                q.run(q.timer,(0x20007800,))
                signed=(abs(max(-2000,min(2000,raw)))+10)//20*(1 if raw>=0 else -1)
                vals={0:75,1:signed,2:signed,3:(signed+100)//2,4:(signed+100)//2}
                for child,v in zip(children,leaves):
                    obj=q.objects[child];role=v.get('role');ch=v.get('channel')
                    if v['kind']=='img':
                        name=v['sprite']
                        if role=='digit':name='d%d_%d'%(ch,f.CHARS.index(str(vals[ch]).rjust(4)[v['col']]))
                        self.assertEqual(obj['asset'],f.asset(key,name),(key,ch,role,raw))
                        if role=='segment':self.assertEqual(bool(obj['flags']&1),vals[ch]<v['threshold'])
                    if role=='needle':self.assertEqual(obj['points'],f.points(v['geom'],vals[ch]))
                self.assertFalse(any(name in ('image_source','add_flag','clear_flag','bar_value','line_points') for name,_ in q.run(q.timer,(0x20007800,))))
            q.put(children[-1]+4,0)
            self.assertEqual([name for name,_ in q.run(q.timer,(0x20007800,))],['native_callback'])
    def test_failed_artwork_allocation_does_not_hide_stock(self):
        for key in f.THEMES:
            for fail in (2,len(f.scene(key))//2,len(f.scene(key))+1):
                q=self.prepare(key,fail);self.assertFalse(q.objects[q.word(PANEL)]['children'])
                self.assertFalse(q.objects[q.word(0x200005d8)]['flags']&1)
    def test_switching_between_old_new_media_and_stock(self):
        import installer
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        from test_startup_animation import asset
        for key in f.THEMES:
            for fast in (False,True):
                old=p.build_patch(self.original,dashboard='custom',layout=t.layout(key),usb_1ms=fast)
                new=p.build_patch(self.original,dashboard="custom",layout=f.layout(key),usb_1ms=fast)
                saved=json.loads(Path(__file__).with_name('legacy-064-faces.json').read_text())
                self.assertEqual(hashlib.sha256(new).hexdigest(),saved[key][int(fast)])
                current=windows_prefix(raw_fixture(self.original))
                for target in (old,new,p.build_patch(self.original,dashboard="custom",layout=f.layout(key),usb_1ms=fast,startup_animation=asset()),new,self.original):
                    current,_,_=installer.plan_transfer(windows_prefix(current),target,self.original)
                    self.assertEqual(current[installer.APP:installer.APP+len(target)],target)
                self.assertEqual(p.inspect_image(new)['layout'],f.layout(key))
                self.assertEqual(p.revert_patch(new),self.original);self.assertLess(len(new),f.PLAYER_OFFSET)
                corrupt=bytearray(new);corrupt[p.FAST_SIZE+134]^=1
                self.assertFalse(p.inspect_image(bytes(corrupt))['recognized'])

