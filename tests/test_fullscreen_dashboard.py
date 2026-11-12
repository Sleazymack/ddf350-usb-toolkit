"""The fullscreen art must be last and opaque; free only our tree on failure."""
import hashlib,json,os,sys,struct,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard_custom as c
import dashboard_faces as faces
import dashboard_fullscreen as lcd
import dashboard_zones as zones
import patch_firmware as p
from test_dashboard_zones import HAVE_ARM,BASE,ROOT,PANEL,RETURN_VALUE
from test_dashboard_six import RAM
if HAVE_ARM:
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
    from test_dashboard_faces import FacesProbe
    class OverlayProbe(FacesProbe):
        def prepare_home(self):
            root=super().prepare_home()
            # The stock 2.0.5 constructor creates the menu object after all trim
            # widgets, including those that have no global pointer.
            kids=self.objects[root]['children'];menu=self.word(lcd.MENU)
            kids.remove(menu);kids.append(menu);self.sync_children(root)
            self.stock=tuple(kids);return root
        def allocate(self,kind,parent):
            addr=super().allocate(kind,parent)
            if hasattr(self,'stock') and kind=='obj' and parent==self.word(ROOT):
                self.put(self.word(addr+8),RAM+0x5300)
            return addr

@unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'needs exact local 2.0.5 and ARM tests')
class FullscreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
    def probe(self,img,fast=False,fail=None):
        cpu=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);cpu.detail=True
        ctor=next(cpu.disasm(img[0x59ae4:0x59ae8],BASE+0x59ae4)).operands[0].imm
        q=OverlayProbe(self,img,p.FAST_SIZE if fast else p.ORIGINAL_SIZE)
        q.ctor=ctor;q.timer=struct.unpack_from('<I',img,0x5850c)[0];q.fail_at=fail
        q.run(ctor,(q.word(lcd.MENU),2),RETURN_VALUE)
        return q
    def test_full_bleed_z_order_geometry_live_sources_and_cleanup(self):
        for key in lcd.THEMES:
            im=p.build_patch(self.original,dashboard=key,usb_1ms=True)
            q=self.probe(im,True);kids=q.objects[q.word(ROOT)]['children']
            self.assertEqual(tuple(kids[:-1]),q.stock);self.assertEqual(kids[-2],q.word(lcd.MENU))
            frame=q.objects[kids[-1]];self.assertEqual(frame['size'],(240,320))
            self.assertEqual(frame['align'],(1,0,0));self.assertEqual(frame['colors'][('bg_color',0)],0)
            self.assertEqual(frame['styles'][(0x21,0)],255);self.assertFalse(frame['flags']&(1|c.NONINTERACTIVE_CLIPPED))
            self.assertFalse(q.objects[q.word(lcd.MENU)]['flags']&1);self.assertFalse(q.objects[q.word(PANEL)]['children'])
            self.assertEqual(lcd.render(key).size,(240,320))
            leaves=lcd.scene(key);self.assertEqual(len(frame['children']),len(leaves))
            q.run(q.ctor,(q.word(lcd.MENU),2),RETURN_VALUE);self.assertEqual(tuple(kids[:-1]),q.stock)
            samples=[
                # The very first zero must also place needles/LEDs at neutral.
                ((0,0,0,0),(0,0,0,0),False),
                # Inner and outer raw edges that previously showed -83/+83 and 9/91.
                ((-1650,1650,-1610,1630),(-100,100,-100,100),True),
                ((1669,-1669,1669,-1649),(100,-100,100,-100),True),
                ((825,-825,815,-805),(50,-50,50,-50),True),
                ((-8,9,-8,8),(0,1,0,0),True),
                ((9,-9,9,-9),(1,-1,1,-1),True),
                ((-2147483648,2147483647,2147483647,-2147483648),(-100,100,100,-100),True),
                ((0,0,0,0),(0,0,0,0),True),
            ]
            for raw,expected,step in samples:
                if step:
                    q.cpu.mem_write(RAM+0x204,struct.pack('<4i',*raw))
                    q.objects[q.word(0x200005cc)]['value']=75;q.run(q.timer,(0x20007800,))
                values=[75 if step else 0,*expected]
                for child,item in zip(frame['children'],leaves):
                    obj=q.objects[child];ch=item.get('channel');role=item.get('role');x,y,w,h=item['box']
                    if role=='bitmap_needle':
                        hand=item['hand'];frame_index=50+((abs(values[ch])+1)//2)*(1 if values[ch]>=0 else -1)
                        name,dx,dy=hand['frames'][frame_index]
                        x,y=hand['cx']+dx,hand['cy']+dy
                        w,h=faces.asset(key,name,True,True,native=True)[:2]
                    self.assertEqual(obj['align'],(1,x,y));self.assertEqual(obj['size'],(w,h))
                    if item['kind']=='img':
                        if role!='bitmap_needle':name=item['sprite']
                        if role=='digit':
                            value=values[ch]
                            text=('+' if ch and value>0 else '')+str(value)
                            name='d%d_%d'%(ch,'0123456789- %+'.index(text.rjust(4)[item['col']]))
                        self.assertEqual(obj['asset'],faces.asset(key,name,True,True,native=True))
                    if role=='needle':self.assertEqual(obj['points'],faces.points(item['geom'],(values[ch]+100)//2))
                for ch in (3,4):
                    leds=[q.objects[child] for child,item in zip(frame['children'],leaves) if item.get('role')=='segment' and item['channel']==ch]
                    if leds:
                        patterns={-100:'1111111100000000',-50:'0000111100000000',-1:'0000000100000000',
                                  0:'0000000000000000',1:'0000000010000000',50:'0000000011110000',
                                  100:'0000000011111111'}
                        self.assertEqual(''.join('0' if obj['flags']&1 else '1' for obj in leds),patterns[values[ch]])
            q.allowed_native=[(BASE+0x59b50,BASE+0x59bb4)];q.run(BASE+0x59b50);q.allowed_native=[]
            self.assertEqual(q.word(ROOT),0);self.assertFalse(q.run(q.timer,(0x20007800,)))
    def test_partial_allocation_preserves_original_chrome(self):
        for key in lcd.THEMES:
            img=p.build_patch(self.original,dashboard=key)
            for fail in (1,2,len(lcd.scene(key))//2,len(lcd.scene(key))+1):
                q=self.probe(img,fail=fail)
                self.assertEqual(tuple(q.objects[q.word(ROOT)]['children']),q.stock)
                self.assertTrue(all(q.objects[ch]['alive'] and not(q.objects[ch]['flags']&1) for ch in q.stock))

    def test_reproduce_report_on_065_and_replay_same_inputs_on_fixed_themes(self):
        for key in lcd.THEMES:
            for fast in (False,True):
                for schema,before in ((5,True),(7,False),(8,False),(9,False)):
                    im=p.build_patch(self.original,dashboard='custom',layout={'schema':schema,'theme':key},usb_1ms=fast)
                    q=self.probe(im,fast)
                    tree=q.objects[q.objects[q.word(ROOT)]['children'][-1]]['children']
                    scene=faces.scene(key,True,not before,native=schema in (8,9),centered=schema==9)
                    caches={v['channel']:q.objects[node] for v,node in zip(scene,tree) if v.get('role')=='cache'}
                    for raw,old,new in [
                        ((-1660,-1660,-1630,-1630),(-83,-83,9,9),(-100,)*4),
                        ((0,0,0,0),(0,0,50,50),(0,)*4),
                        ((1660,1660,1640,1640),(83,83,91,91),(100,)*4)]:
                        q.cpu.mem_write(RAM+0x204,struct.pack('<4i',*raw));q.run(q.timer,(0x20007800,))
                        self.assertEqual(tuple(caches[ch]['value'] for ch in range(1,5)),old if before else new)
    def test_lower_grid_never_touches_upper_objects(self):
        s=zones.DEFAULT_LOWER
        for include_battery in (False,True):
            items=s['widgets'] if not include_battery else [dict(zones.DEFAULT['widgets'][0],zone='B')]
            img=p.build_patch(self.original,dashboard='custom',layout={**s,'widgets':items})
            q=self.probe(img);panel=q.objects[q.word(PANEL)]
            self.assertIsNone(panel['size']);self.assertIsNone(panel['align'])
            self.assertTrue(all(not(q.objects[q.word(ptr)]['flags']&1) for ptr in (*zones.UPPER_NATIVE,lcd.MENU)))
            for node in panel['children']:
                obj=q.objects[node];_,x,y=obj['align'];w,h=obj['size']
                self.assertTrue(0<=x<x+w<=215 and 0<=y<y+h<=100)
            self.assertEqual(p.revert_patch(img),self.original)
    def test_old_fullscreen_lower_and_rollback_in_both_usb_modes(self):
        import installer
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        from test_startup_animation import asset
        for key in lcd.THEMES:
            for fast in (False,True):
                old=p.build_patch(self.original,dashboard='custom',layout={'schema':5,'theme':key},usb_1ms=fast)
                saved=json.loads(Path(__file__).with_name('legacy-065-faces.json').read_text())
                self.assertEqual(hashlib.sha256(old).hexdigest(),saved[key][int(fast)])
                previous=p.build_patch(self.original,dashboard='custom',layout={'schema':7,'theme':key},usb_1ms=fast)
                saved_066=json.loads(Path(__file__).with_name('legacy-066-faces.json').read_text())
                self.assertEqual(hashlib.sha256(previous).hexdigest(),saved_066[key][int(fast)])
                v067=p.build_patch(self.original,dashboard='custom',layout={'schema':8,'theme':key},usb_1ms=fast)
                saved_067=json.loads(Path(__file__).with_name('legacy-067-faces.json').read_text())
                self.assertEqual(hashlib.sha256(v067).hexdigest(),saved_067[key][int(fast)])
                new=p.build_patch(self.original,dashboard=key,usb_1ms=fast)
                self.assertEqual(p.inspect_image(new)['layout'],lcd.layout(key))
                self.assertEqual(p.revert_patch(new),self.original)
                current=windows_prefix(raw_fixture(old))
                for img in (previous,v067,new,p.build_patch(self.original,dashboard=key,usb_1ms=fast,startup_animation=asset()),
                            p.build_patch(self.original,dashboard='custom',layout=zones.DEFAULT_LOWER,usb_1ms=fast),self.original):
                    current,_,_=installer.plan_transfer(windows_prefix(current),img,self.original)
                    self.assertEqual(current[installer.APP:installer.APP+len(img)],img)

    def test_usb_power_tracks_live_frames_and_reverts_to_battery(self):
        for key in lcd.THEMES:
            for fast in (False,True):
                q=self.probe(p.build_patch(self.original,dashboard=key,usb_1ms=fast),fast)
                children=q.objects[q.objects[q.word(ROOT)]['children'][-1]]['children']
                widgets=list(zip(lcd.scene(key),[q.objects[n] for n in children]))
                battery=next(obj for item,obj in widgets if item.get('role')=='cache' and item['channel']==0)
                badge=next(obj for item,obj in widgets if item.get('role')=='usb_source')
                digits=[(item,obj) for item,obj in widgets if item.get('role')=='digit' and item['channel']==0]
                native=q.objects[q.word(0x200005cc)]
                def tick(expected,live):
                    q.run(q.timer,(0x20007800,))
                    self.assertEqual(battery['value'],expected)
                    self.assertEqual(not bool(badge['flags']&1),live)
                    for item,obj in digits:
                        s=str(expected).rjust(4)[item['col']]
                        self.assertEqual(obj['asset'],faces.asset(key,f'd0_{faces.CHARS.index(s)}',True,True,native=True))
                native['value']=80;tick(80,False)
                q.put(lcd.USB_CONFIG_STATE,5)
                q.cpu.mem_map(lcd.USB_CLOCK_ENABLE & ~4095,4096)
                tick(80,False)  # A gated USB register is still unmapped.
                q.put(lcd.USB_CLOCK_ENABLE,1<<23)
                q.cpu.mem_map(lcd.USB_FRAME_NUMBER & ~4095,4096)
                q.put(lcd.USB_FRAME_NUMBER,0x1ffe);tick(80,False);tick(80,False)
                q.put(lcd.USB_FRAME_NUMBER,0x1fff);tick(100,True)
                q.put(lcd.USB_FRAME_NUMBER,0);tick(100,True)  # frame rollover
                native['value']=47;tick(100,True);tick(100,True);tick(47,False)
                native['value']=100;tick(100,False)  # Equal readings still require changing source.
                q.put(lcd.USB_FRAME_NUMBER,32);tick(100,True)
                q.put(lcd.USB_CONFIG_STATE,1);tick(100,False)
                native['value']=54;tick(54,False)

class NativePixelTests(unittest.TestCase):
    def test_all_new_sprites_use_binary_coverage_and_needles_stay_inside_lcd(self):
        for key,face in faces.face_bank(True,True,native=True).items():
            for name in face['sprites']:
                width,height,bits,data=faces.asset(key,name,True,True,native=True)
                self.assertTrue(set(data[3:4*(1<<bits):4])<={0,255})
                self.assertTrue(0<width<=240 and 0<height<=320)
            for hand in face['hands']:
                self.assertEqual(len(hand['frames']),101)
                for name,dx,dy in hand['frames']:
                    w,h=face['sprites'][name][:2];x,y=hand['cx']+dx,hand['cy']+dy
                    self.assertTrue(0<=x<x+w<=240 and 0<=y<y+h<=320)

