"""Three live native presets: bounded geometry, actual Thumb, no hardware."""
import copy
import os
from pathlib import Path
import struct
import sys
import tkinter as tk
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard_custom as c
import dashboard_themes as t
import patch_firmware as p
import app
import wizard
from test_dashboard_zones import HAVE_ARM,BASE,ROOT,PANEL,RETURN_VALUE
from test_dashboard_six import signed,RAM


class ThemeContractTests(unittest.TestCase):
    def test_three_additional_presets_and_fixed_bounded_contract(self):
        self.assertEqual(len(app.EDITIONS),6)
        self.assertEqual(tuple(row[0] for row in app.EDITIONS[-3:]),t.THEMES)
        for key in t.THEMES:
            spec=t.layout(key)
            self.assertEqual(c.parse_layout(c.canonical_json(spec)),spec)
            leaves=t.scene(key)
            self.assertLessEqual(len(leaves),t.MAX_LEAVES)
            self.assertEqual({v['channel'] for v in leaves if v.get('role')=='value'},set(range(5)))
            for item in leaves:
                x,y,w,h=item['box']
                self.assertTrue(0<=x<x+w<=215 and 0<=y<y+h<=270)
        for bad in ({'schema':3,'theme':'unknown'},{'schema':3,'theme':'strip_drift','script':'x'},
                    {'schema':True,'theme':'strip_drift'}):
            with self.assertRaises(ValueError):c.validate_layout(bad)

    def test_wizard_six_choices_and_distinct_previews(self):
        root=tk.Tk();root.overrideredirect(True);root.attributes('-alpha',0)
        ui=wizard.Wizard(root)
        try:
            ui.step=2;ui.render();root.update()
            keys=[e[0] for e in app.EDITIONS]+['custom']
            for i,key in enumerate(keys):
                self.assertEqual(ui.dashboard.get(),key);self.assertEqual(ui.gallery_count.cget('text'),f'{i+1:02} / 07')
                ui.gallery_next.invoke()
            self.assertEqual(ui.dashboard.get(),'original')
            ui.gallery_prev.invoke();self.assertEqual(ui.dashboard.get(),'custom')
            ui.next();self.assertIsNotNone(ui.inline_editor);ui.previous();root.update()
            self.assertEqual(ui.dashboard.get(),'custom')
            ui.scroll_gallery('moveto',0.45);self.assertEqual(ui.dashboard.get(),keys[3])
            ui.gallery_canvas.event_generate('<MouseWheel>',delta=-120);root.update()
            self.assertEqual(ui.dashboard.get(),keys[4])
            ui.gallery_canvas.event_generate('<ButtonPress-1>',x=20,y=30)
            ui.gallery_canvas.event_generate('<ButtonRelease-1>',x=85,y=30);root.update()
            self.assertEqual(ui.dashboard.get(),keys[3])
            ui.gallery_canvas.focus_force();root.update();ui.gallery_canvas.event_generate('<Right>');root.update()
            self.assertEqual(ui.dashboard.get(),keys[4])
            counts=[]
            for key in t.THEMES:
                canvas=tk.Canvas(root,width=215,height=270);canvas.pack();root.update()
                t.paint(canvas,key);counts.append(len(canvas.find_all()));canvas.destroy()
                ui.select_dashboard(key);ui.step=3;ui.render();root.update()
                self.assertIsNone(ui.inline_editor)
            self.assertEqual(len(set(counts)),3)
        finally:ui.close()


if HAVE_ARM:
    from test_dashboard_zones import ZoneProbe
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
    from unicorn.arm_const import UC_ARM_REG_SP
    class ThemeProbe(ZoneProbe):
        def __init__(self,*args):
            super().__init__(*args)
            self.api_names[t.LINE_CREATE-BASE]='line_create'
            self.api_names[t.LINE_POINTS-BASE]='line_points'
        def allocate(self,kind,parent):
            index=self.next_index;self.next_index+=1
            address=RAM+0x10000+index*0x60;spec=RAM+0x4000+index*0x10;array=RAM+0x6000+index*0x100
            self.test.assertLess(array+0x100,RAM+0x10000)
            self.put(address,t.CLASS[kind]);self.put(address+4,parent);self.put(address+8,spec)
            self.put(spec,array);self.put(spec+4,0)
            self.objects[address]={'kind':kind,'parent':parent,'children':[],'alive':True,'text':'','value':0,
                'size':None,'align':None,'flags':0x80012,'styles':{},'colors':{},'removed_parts':[]}
            self.put(address+0x1c,0x80012)
            if parent:self.objects[parent]['children'].append(address);self.sync_children(parent)
            return address
        def on_code(self,cpu,address,size,unused):
            if address!=t.LINE_POINTS:return super().on_code(cpu,address,size,unused)
            args=[cpu.reg_read(r) for r in self.argument_regs]
            self.test.assertEqual(cpu.reg_read(UC_ARM_REG_SP)%8,0)
            self.test.assertEqual(args[2],2)
            self.test.assertTrue(self.new_start<=args[1]<BASE+len(self.image))
            obj=self.objects[args[0]];self.test.assertTrue(obj['alive']);self.test.assertEqual(obj['kind'],'line')
            obj['points']=struct.unpack('<4h',cpu.mem_read(args[1],8))
            self.calls.append(('line_points',tuple(args)));self.return_api(0)


@unittest.skipUnless(HAVE_ARM and os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local input and ARM packages required')
class ThemeFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();p._require_original(cls.original)
    def probe(self,key,fast=False,construct=True):
        image=p.build_patch(self.original,dashboard="custom",layout=t.layout(key),usb_1ms=fast)
        decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);decoder.detail=True
        ctor=next(decoder.disasm(image[0x59ae4:0x59ae8],BASE+0x59ae4)).operands[0].imm
        scene=ThemeProbe(self,image,p.FAST_SIZE if fast else p.ORIGINAL_SIZE)
        scene.constructor=ctor;scene.timer=struct.unpack_from('<I',image,0x5850c)[0]
        if construct:scene.run(ctor,(scene.word(0x200005d8),2),RETURN_VALUE)
        return scene
    def test_expected_classes_are_loaded_by_the_actual_native_creators(self):
        from capstone.arm import ARM_REG_PC,ARM_REG_R0,ARM_OP_MEM
        decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);decoder.detail=True
        for kind,offset in (('obj',0x4c1fc),('bar',0x40014),('arc',0x3f1b4),('label',0x49300),('line',0x4a778)):
            loads=[i for i in decoder.disasm(self.original[offset:offset+32],BASE+offset)
                if i.mnemonic=='ldr' and len(i.operands)==2 and i.operands[0].reg==ARM_REG_R0
                and i.operands[1].type==ARM_OP_MEM and i.operands[1].mem.base==ARM_REG_PC]
            self.assertTrue(loads)
            pointer=((loads[0].address+4)&~3)+loads[0].operands[1].mem.disp
            self.assertEqual(struct.unpack_from('<I',self.original,pointer-BASE)[0],t.CLASS[kind])
    def test_exact_original_reconstruction_scope_and_media_switching(self):
        from test_startup_animation import asset
        from test_installer import raw_fixture
        from test_installer_switching import windows_prefix
        import installer
        current=windows_prefix(raw_fixture(self.original))
        for fast in (False,True):
            for key in t.THEMES:
                image=p.build_patch(self.original,dashboard="custom",layout=t.layout(key),usb_1ms=fast)
                self.assertEqual(p.revert_patch(image),self.original)
                self.assertEqual(p.inspect_image(image)['layout'],t.layout(key))
                base=p.build_patch(self.original,usb_1ms=fast)
                differences={n for n,(a,b) in enumerate(zip(image,base)) if a!=b}
                self.assertTrue(differences<=set(range(0x59ae4,0x59ae8))|set(range(0x5850c,0x58510)))
                wrapped=p.build_patch(self.original,dashboard="custom",layout=t.layout(key),usb_1ms=fast,startup_animation=asset())
                for target in (image,wrapped,image,self.original):
                    current=windows_prefix(current)
                    before=current;current,_,_=installer.plan_transfer(current,target,self.original)
                    self.assertEqual(current[:installer.APP],before[:installer.APP])
                    self.assertEqual(current[installer.APP:installer.APP+len(target)],target)
                bad=bytearray(image);bad[-40]^=1
                self.assertFalse(p.inspect_image(bytes(bad))['recognized'])
    def test_live_values_segments_needles_battery_and_repeated_values(self):
        for fast in (False,True):
            for key in t.THEMES:
                probe=self.probe(key,fast);leaves=t.scene(key)
                panel=probe.word(PANEL);root=probe.objects[panel]['children'][0]
                children=probe.objects[root]['children']
                self.assertEqual(len(children),len(leaves))
                self.assertEqual(probe.creations,len(leaves)+1)
                for raw in (-2500,-2000,-1010,-10,0,10,710,1300,2000,2500):
                    probe.cpu.mem_write(RAM+0x204,struct.pack('<6i',raw,raw,raw,raw,0,0))
                    probe.objects[probe.word(0x200005cc)]['value']=75
                    probe.run(probe.timer,(0x20007800,))
                    # Native helper rounds exact halves away from zero.
                    value=(abs(max(-2000,min(2000,raw)))+10)//20*(1 if raw>=0 else -1)
                    for item,child in zip(leaves,children):
                        obj=probe.objects[child]
                        if item.get('role')=='value':self.assertEqual(obj['text'],f"{75 if item['channel']==0 else value}%")
                        elif item.get('role')=='segment':
                            color=c.native_color(item['color'] if value>=item['threshold'] else t.TRACK)
                            observed=obj['styles'].get((0x52,0)) if item['kind']=='arc' else obj['colors'].get(('bg_color',0))
                            self.assertEqual(observed,color)
                        elif item.get('role')=='needle':
                            cx,cy=item['center'];expected=(cx,cy,*t.point(cx,cy,item['radius'],135+(value+100)*270/200))
                            self.assertEqual(obj['points'],expected)
                    calls=probe.run(probe.timer,(0x20007800,))
                    self.assertFalse(any(name in ('text_fmt','bar_value','line_points','bg_color','style') for name,_ in calls))
                self.assertFalse(probe.objects[probe.word(0x200005d8)]['flags']&1)
    def test_every_partial_allocation_falls_back_and_native_cleanup_owns_all(self):
        for key in t.THEMES:
            for failed in range(1,len(t.scene(key))+2):
                probe=self.probe(key,construct=False);probe.fail_at=failed
                alive={n for n,obj in probe.objects.items() if obj['alive']}
                probe.run(probe.constructor,(probe.word(0x200005d8),2),RETURN_VALUE)
                self.assertEqual({n for n,obj in probe.objects.items() if obj['alive']},alive)
                self.assertFalse(probe.objects[probe.word(PANEL)]['children'])
            probe=self.probe(key)
            probe.allowed_native=[(BASE+0x59b50,BASE+0x59bb4)];probe.run(BASE+0x59b50);probe.allowed_native=[]
            self.assertEqual(probe.word(ROOT),0);self.assertEqual(probe.run(probe.timer,(0x20007800,)),[])
    def test_wrong_child_ownership_or_class_blocks_updates(self):
        for key in t.THEMES:
            for fault in ('parent','class','count'):
                probe=self.probe(key);root=probe.objects[probe.word(PANEL)]['children'][0]
                child=probe.objects[root]['children'][-1]
                if fault=='parent':probe.put(child+4,probe.word(PANEL))
                elif fault=='class':probe.put(child,0)
                else:probe.put(probe.word(root+8)+4,1)
                self.assertEqual([name for name,_ in probe.run(probe.timer,(0x20007800,))],['native_callback'])


if __name__=='__main__':unittest.main()
