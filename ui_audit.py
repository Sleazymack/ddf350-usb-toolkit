"""Offline inspection of our own Tk widgets; no USB, flashing or startup writes.

Checks active notebook pages, ancestor clipping, unmapped managed controls and
requested control height. A bounding box inside the root alone is insufficient.
"""
import json
from pathlib import Path
import tkinter as tk
import tkinter.font as font
import time
import i18n

CONTROL_CLASSES={'Button','TButton','Checkbutton','TCheckbutton','Radiobutton',
                 'TRadiobutton','TCombobox','Entry','TEntry','Label','TLabel','Text'}


def active_widgets(parent):
    for child in parent.winfo_children():
        if parent.winfo_class()=='TNotebook' and str(child)!=parent.select():continue
        yield child
        yield from active_widgets(child)


def label(widget):
    try:
        if widget.winfo_class()=='TCombobox':return widget.get()
        variable=widget.cget('textvariable')
        if variable:return str(widget.getvar(str(variable)))
        return str(widget.cget('text'))
    except tk.TclError:return widget.winfo_class()


def inspect(root):
    from ui_layout import ScrollArea
    root.update()
    issues=[]
    for widget in active_widgets(root):
        cls=widget.winfo_class()
        if cls=='Canvas' and widget.winfo_ismapped():
            for item in widget.find_all():
                if widget.type(item)!='text':continue
                box=widget.bbox(item)
                if box and (box[0]<-3 or box[1]<-3 or box[2]>widget.winfo_width()+3 or box[3]>widget.winfo_height()+3):
                    issues.append({'control':widget.itemcget(item,'text'),'class':'CanvasText','reasons':['text outside illustration'],
                                   'bounds':box,'canvas':[widget.winfo_width(),widget.winfo_height()]})
        if cls=='TNotebook' and widget.winfo_ismapped():
            seen=set()
            for y in range(3,min(60,widget.winfo_height()),4):
                for x in range(2,widget.winfo_width(),4):
                    try:seen.add(widget.index(f'@{x},{y}'))
                    except tk.TclError:pass
            if seen!=set(range(len(widget.tabs()))):issues.append({'class':'TNotebook','reasons':['not all tabs reachable'],'visible_tabs':sorted(seen)})
        if cls not in CONTROL_CLASSES or not widget.winfo_manager():continue
        ancestors=[];ancestor=widget.master
        while ancestor is not None:
            ancestors.append(ancestor)
            if ancestor is root:break
            ancestor=ancestor.master
        # A hidden page/header is not a candidate; hidden packed siblings inside
        # a visible container ARE candidates and must not silently be skipped.
        if any(not a.winfo_ismapped() for a in ancestors):continue
        for a in ancestors:
            if isinstance(a,ScrollArea):a.reveal(widget)
        root.update_idletasks()
        name=label(widget);reasons=[]
        if not widget.winfo_ismapped():reasons.append('managed control is unmapped')
        else:
            x,y=widget.winfo_rootx(),widget.winfo_rooty();w,h=widget.winfo_width(),widget.winfo_height()
            if h+2<widget.winfo_reqheight():reasons.append('control height clipped')
            if cls not in ('Label','TLabel','Text') and w+2<widget.winfo_reqwidth():reasons.append('control width clipped')
            if cls=='TCombobox':
                text_font=font.Font(root=widget,font=widget.cget('font'))
                if text_font.measure(widget.get())>w-26:reasons.append('selected value clipped')
            viewport_heights=[a.canvas.winfo_height() for a in ancestors if isinstance(a,ScrollArea)]
            readable_by_scrolling=cls in ('Label','TLabel') and viewport_heights and h>min(viewport_heights)
            allow_vertical_clip=False
            for a in ancestors:
                ax,ay=a.winfo_rootx(),a.winfo_rooty()
                if a.winfo_class()=='Canvas' and isinstance(a.master,ScrollArea):
                    allow_vertical_clip=bool(readable_by_scrolling)
                if x<ax-2 or (y<ay-2 and not allow_vertical_clip) or x+w>ax+a.winfo_width()+2 or (y+h>ay+a.winfo_height()+2 and not allow_vertical_clip):
                    reasons.append('outside '+a.winfo_class());break
        if reasons:issues.append({'control':name,'class':cls,'reasons':reasons,
                                 'actual':[widget.winfo_width(),widget.winfo_height()],
                                 'requested':[widget.winfo_reqwidth(),widget.winfo_reqheight()]})
    return issues


def collect(widths=(640,800),scales=(4/3,5/3,2,8/3)):
    from wizard import Wizard
    from unittest import mock
    cases=[]
    original_language=i18n.language()
    for language in ('fr','en'):
        i18n.set_language(language)
        for scale in scales:
            for width in widths:
                root=tk.Tk();root.overrideredirect(True);root.attributes('-alpha',0)
                callback_errors=[]
                root.report_callback_exception=lambda kind,value,trace:callback_errors.append(f'{kind.__name__}: {value}')
                root.tk.call('tk','scaling',scale)
                ui=Wizard(root)
                root.minsize(width,width*3//4);root.maxsize(width,width*3//4);root.geometry(f'{width}x{width*3//4}')
                def record(page):
                    issues=inspect(root)
                    if ui.step==4 and not ui.pc_mode:
                        if ui.body_view._bar_visible or ui.body_view.canvas.yview()!=(0.0,1.0):
                            issues.append({'control':'Startup screen','reasons':['vertical scroll needed']})
                        if ui.media_candidate or ui.startup_media:
                            c=ui.preview_canvas
                            box=c.bbox('frame') if c else None
                            if not box or box[0]<0 or box[1]<0 or box[2]>c.winfo_width() or box[3]>c.winfo_height():
                                issues.append({'control':'Startup preview','reasons':['preview missing or clipped']})
                    if callback_errors:
                        issues.append({'callback_errors':list(callback_errors)});callback_errors.clear()
                    cases.append({'language':language,'scale_percent':round(scale*75),'width':width,'page':page,'issues':issues})
                try:
                    for step in range(1,8):
                        ui.step=step;ui.render();record(f'radio-{step}')
                    from dashboard_themes import THEMES
                    for key in THEMES:
                        ui.dashboard.set(key);ui.step=3;ui.render();record('theme-'+key)
                    ui.dashboard.set('original')
                    import startup_media
                    import io
                    from PIL import Image
                    stream=io.BytesIO();Image.new('RGB',(32,48),'cyan').save(stream,format='PNG')
                    ui.startup_media=startup_media.from_bytes(stream.getvalue(),name='startup-example.png')
                    ui.step=4;ui.render();record('startup-media-selected')
                    ui.media_source=('startup-example.png',stream.getvalue());ui.media_candidate=ui.startup_media
                    ui.media_candidate_valid=True;ui.media_pending=True;ui.render();record('startup-media-awaiting-incorporation')
                    ui.media_candidate_valid=False;ui.render();record('startup-media-settings-changed')
                    ui.media_loading=True;ui.render();record('startup-media-converting');ui.media_loading=False
                    ui.clear_startup_media()
                    ui.choose_custom();record('editor-gauge')
                    if hasattr(ui.inline_editor,'notebook'):
                        for n,tab in enumerate(ui.inline_editor.notebook.tabs()):
                            ui.inline_editor.notebook.select(tab);record(f'editor-tab-{n}')
                    ui.show_pc_mode(start_reader=False);record('pc')
                    from pc.ddf350_hid import Channels
                    for value in (0,2047):
                        ui.game_values=Channels(value,value);ui.game_last_data=time.monotonic()
                        ui.poll_game_reader();record(f'pc-input-{value}')
                    ui.pc_mode=False;ui.step=6;ui.render();ui.finish_error('Erreur de test / Test error : '+('bloc USB indisponible · '*20));record('installation-error')
                    ui.show_radio_mode();ui.step=2;ui.render()
                    with mock.patch.object(i18n,'save_language'):
                        ui.select_language('en' if language=='fr' else 'fr');record('language-dropdown')
                        ui.select_language(language)
                    ui.select_dashboard('custom');record('gallery-custom')
                    ui.step=1
                    ui.source.set('');ui.version_confirmed=True;ui.render();record('firmware-source')
                finally:ui.busy=False;ui.close()
    i18n.set_language(original_language)
    return {'schema':1,'result':'PASS' if not any(c['issues'] for c in cases) else 'FAIL',
            'cases':cases,'cases_count':len(cases),'radio_accessed':False,'startup_written':False}


def save(destination):
    import patch_firmware as p
    target=p.validate_local_path(destination,output=True);p._check_local_volume(target,'UI audit')
    report=collect()
    with target.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2,ensure_ascii=False)
    return report
