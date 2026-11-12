"""Whole-page clipping regression including nested scrolling and PC startup."""
import sys
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wizard
import ui_audit
from ui_layout import ScrollArea


class LayoutAuditTests(unittest.TestCase):
    def test_all_pages_both_languages_and_four_text_scales(self):
        result=ui_audit.collect()
        failures=[c for c in result['cases'] if c['issues']]
        self.assertEqual(result['cases_count'],400)
        self.assertEqual(failures,[],str(failures)[:4000])
        self.assertEqual(result['result'],'PASS')

    def test_pc_startup_navigation_keeps_optional_radio_media_separate(self):
        root=tk.Tk();root.overrideredirect(True);root.attributes('-alpha',0)
        with mock.patch('pc_startup.is_enabled',return_value=True):
            ui=wizard.Wizard(root)
            try:
                for enabled in (False,True):
                    ui.show_pc_mode(start_reader=False)
                    self.assertTrue(ui.pc_startup_enabled.get())
                    ui.pc_startup_enabled.set(enabled)
                    ui.show_radio_mode()
                    self.assertFalse(hasattr(ui,'startup_checkbox'))
                    self.assertIsNone(ui.startup_media)
            finally:ui.close()

    def test_rapid_page_changes_leave_no_layout_callbacks_or_bindings(self):
        root=tk.Tk();root.overrideredirect(True);root.attributes('-alpha',0);errors=[]
        root.report_callback_exception=lambda kind,value,trace:errors.append(str(value))
        ui=wizard.Wizard(root)
        try:
            counts=[]
            for _ in range(5):
                ui.choose_custom();root.update()
                counts.append(tuple(sum(bool(line.strip()) for line in root.bind(s).splitlines()) for s in ('<Configure>','<FocusIn>','<MouseWheel>')))
                ui.previous();ui.choose_custom();ui.previous();root.update()
            self.assertTrue(all(value==counts[0] for value in counts))
            self.assertEqual(errors,[])
        finally:ui.close()

    def test_nested_wheel_routes_to_inner_then_outer_and_focus_reveals(self):
        root=tk.Tk();root.overrideredirect(True);root.attributes('-alpha',0);root.geometry('360x240')
        outer=ScrollArea(root,bg='#101924');outer.pack(fill='both',expand=True)
        inner=ScrollArea(outer.content,bg='#101924',height=100)
        inner.pack(fill='x')
        buttons=[]
        for n in range(12):
            button=tk.Button(inner.content,text=str(n));button.pack(fill='x');buttons.append(button)
        tk.Frame(outer.content,height=500).pack(fill='x');root.update()
        try:
            event=SimpleNamespace(widget=buttons[0],delta=-120)
            before=outer.canvas.yview()
            self.assertIsNone(outer.wheel(event));self.assertEqual(inner.wheel(event),'break')
            self.assertEqual(outer.canvas.yview(),before)
            inner.canvas.yview_moveto(1);root.update()
            self.assertEqual(outer.wheel(event),'break');self.assertNotEqual(outer.canvas.yview(),before)
            inner.focus_changed(SimpleNamespace(widget=buttons[0]));root.update()
            y=buttons[0].winfo_rooty();self.assertGreaterEqual(y,inner.canvas.winfo_rooty())
            self.assertLessEqual(y+buttons[0].winfo_height(),inner.canvas.winfo_rooty()+inner.canvas.winfo_height())
        finally:root.destroy()


if __name__=='__main__':unittest.main()
