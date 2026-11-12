"""One task per page, with an explicit installation action."""
import copy
import json
import os
from pathlib import Path
import queue
import threading
import uuid
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from datetime import datetime
import i18n
from i18n import tr

from app import Application, EDITIONS, BG, PANEL, INK, MUTED, ACCENT
import patch_firmware as p
import installer
from ui_layout import ScrollArea,wrap_to_parent,wrap_in_control


class Wizard(Application):
    def __init__(self, root, *, auto_reader=False, enable_tray=False):
        self.step=1
        self.identity=None
        self.worker_handle=None
        self.job_directory=None
        self.target=None
        self.last_phase=None
        self.inline_editor=None
        self.log_view=None
        self.log_offset=0
        self.log_pending=b''
        self.log_lines=[]
        self.game_events=queue.Queue(maxsize=128)
        self.game_reader=None
        self.game_last_data=None
        self.game_values=None
        self.game_enabled=auto_reader
        self.pc_mode=False
        self.pc_panels=[]
        self.tray=None
        self.tray_events=queue.Queue()
        self.hide_requested=False
        self.startup_media=None
        self.media_source=None
        self.media_candidate=None
        self.media_candidate_valid=False
        self.media_pending=False
        self.media_loading=False
        self.preview_after=None
        self.preview_images=[]
        self.preview_canvas=None
        self.media_panel=None
        self.preview_signature=None
        super().__init__(root)
        self.version_confirmed=False
        self.forward.configure(state='disabled')
        width=min(800,self.root.winfo_screenwidth()-48,int((self.root.winfo_screenheight()-110)*4/3))
        width=max(400,width//4*4);height=width*3//4
        self.root.minsize(width,height)
        self.root.maxsize(width,height)
        self.root.geometry(f'{width}x{height}')
        self.root.resizable(False,False)
        self.status_label.configure(wraplength=width-40)
        self.root.title(tr('DDF-350 · Personnaliser et jouer')+' · '+p.VERSION.split('-')[0])
        self.root.protocol('WM_DELETE_WINDOW',self.window_close)
        if enable_tray:
            from sync_tray import TrayIcon
            self.tray=TrayIcon(self.tray_events)
            try:self.tray.start()
            except OSError as error:
                self.tray=None;self.status.set(str(error))
            self.root.bind('<Unmap>',self.on_minimize,add='+')
        self.status.set('')
        if auto_reader:self.start_game_reader()

    def _build(self):
        self.version_confirmed=False
        self.outer=tk.Frame(self.root,bg=BG)
        self.outer.pack(fill='both',expand=True,padx=16,pady=12)
        self.outer.columnconfigure(0,weight=1)
        self.outer.rowconfigure(3,weight=1)
        header=tk.Frame(self.outer,bg=BG);header.grid(row=0,column=0,sticky='ew')
        branding=tk.Frame(header,bg=BG);branding.pack(side='left')
        self.brand_label=super().label(branding,'DDF-350',size=16,bold=True)
        self.brand_label.pack(side='left')
        navigation=tk.Frame(header,bg=BG);navigation.pack(side='right');self.navigation=navigation
        self.radio_button=self.action(navigation,'Radio',self.show_radio_mode,wrap=False)
        self.radio_button.grid(row=0,column=0,sticky='ew',padx=(0,6))
        self.play_button=self.action(navigation,'PC',self.show_pc_mode,wrap=False)
        self.play_button.grid(row=0,column=1,sticky='ew')
        self.language_combo=ttk.Combobox(navigation,values=('English','Français'),state='readonly',width=9,font=('Segoe UI',10))
        self.language_combo.current(0 if i18n.language()=='en' else 1)
        self.language_combo.grid(row=0,column=2,sticky='e',padx=(8,0))
        self.language_combo.bind('<<ComboboxSelected>>',lambda _:self.select_language({'English':'en','Français':'fr'}[self.language_combo.get()]))
        self.step_label=self.label(self.outer,'',size=10,color=ACCENT)
        self.step_label.grid(row=1,column=0,sticky='w',pady=(8,3))
        self.body_view=ScrollArea(self.outer,bg=BG)
        self.body_view.grid(row=3,column=0,sticky='nsew')
        self.title_label=self.label(self.body_view.content,'',size=16,bold=True)
        self.title_label.pack(fill='x',pady=(0,8))
        self.body=tk.Frame(self.body_view.content,bg=BG)
        self.body.pack(fill='both',expand=True)
        self.game_status=i18n.StringVar(value='Lecture CH1/CH2 · disponible après branchement USB normal')
        self.game_label=self.label(self.outer,'',size=9,color=MUTED)
        self.game_label.configure(textvariable=self.game_status)
        self.game_label.grid(row=4,column=0,sticky='ew',pady=(4,0))
        self.status_label=tk.Label(self.body_view.content,textvariable=self.status,bg=BG,fg=INK,
            font=('Segoe UI',9),justify='left',anchor='w',wraplength=740)
        self.status_label.pack(fill='x',pady=(4,4))
        self.status.trace_add('write',self.status_changed)
        footer=tk.Frame(self.outer,bg=BG);footer.grid(row=6,column=0,sticky='ew')
        self.back=ttk.Button(footer,text=tr('Retour'),command=self.previous)
        self.back.pack(side='left',ipady=4)
        self.forward=tk.Button(footer,text=tr('Continuer'),command=self.next,bg=ACCENT,fg=BG,
            font=('Segoe UI',10,'bold'),relief='flat',padx=18,pady=7)
        self.forward.pack(side='right')
        wrap_to_parent(self.game_label,self.outer,12)
        for label in (self.title_label,self.status_label):wrap_to_parent(label,self.body_view.content,12)
        self.render()

    def status_changed(self,*_):
        if self.closed:return
        if self.step==4 and not self.pc_mode:
            self.status_label.pack_forget()
            if self.media_panel:self.media_panel.show_notice(self.status.get())
            return
        if self.status.get():self.status_label.pack(fill='x',pady=(4,4))
        else:self.status_label.pack_forget()
        self.body_view.schedule()

    def action(self,parent,text,command,wrap=True):
        button=tk.Button(parent,text=tr(text),command=command,bg=PANEL,fg=INK,
            activebackground=ACCENT,activeforeground=BG,font=('Segoe UI',10),
            relief='flat',padx=10,pady=6,justify='left',anchor='w',wraplength=400 if wrap else 0)
        return wrap_in_control(button) if wrap else button

    def label(self,parent,text,**kwargs):
        label=super().label(parent,text,**kwargs)
        return wrap_to_parent(label,parent,16)

    def text(self,text):
        self.label(self.body,text,size=10,color=MUTED,justify='left',wraplength=700).pack(anchor='w',pady=(0,10))

    def render(self):
        self.stop_startup_preview()
        self.media_panel=None
        self.inline_editor=None
        self.log_view=None
        for child in self.body.winfo_children():child.destroy()
        self.body_view.set_fill(self.step==3 and self.dashboard.get()=='custom' and not self.pc_mode)
        self.body_view.fill_min_height=round(260*float(self.root.tk.call('tk','scaling'))/(4/3)) if self.body_view.fill else 1
        self.body_view.canvas.yview_moveto(0)
        self.cards=[]
        self.controls=[]
        self.pc_panels=[]
        compact_startup=self.step==4 and not self.pc_mode and self.needs_media_chrome()
        self.set_media_chrome(compact_startup)
        if self.pc_mode:
            self.render_pc_mode()
            return
        self.step_label.configure(text=tr(f'ÉTAPE {self.step} / 7'))
        titles=['Personnaliser la télécommande','Choisir le dashboard','Personnaliser','Écran de démarrage','Brancher la radio','Installer sur la radio','Redémarrer et essayer']
        self.title_label.configure(text=tr(titles[self.step-1]))
        if compact_startup:self.step_label.configure(text=tr('ÉTAPE 4 / 7')+'   ·   '+tr(titles[3]))
        self.back.configure(state='disabled' if self.step in (1,7) or self.busy else 'normal')
        self.forward.configure(text=tr('Installer sur la radio' if self.step==6 else 'Réduire pour jouer' if self.step==7 else 'Continuer'),
                               state='disabled' if self.busy else 'normal')
        self.status.set('')
        if self.step==1:
            if self.version_confirmed and not self.source.get():
                self.render_firmware_source()
                return
            self.text('Crée ton dashboard, puis installe-le sur la radio depuis cette application.\nPour commencer, vérifie la version dans les informations de la radio : HW 1.0 / logiciel 2.0.5.')
            self.action(self.body,'1 · Modifier le dashboard · ma radio est en 2.0.5 / HW 1.0',self.confirm_version).pack(fill='x',anchor='w',ipady=12,pady=10)
            self.pc_button=self.action(self.body,'2 · Activer la télécommande sur PC · CH1 / CH2',self.show_pc_mode)
            self.pc_button.pack(fill='x',anchor='w',ipady=10,pady=(10,0))
            self.forward.configure(state='normal' if self.version_confirmed else 'disabled')
        elif self.step==2:
            self.build_gallery()
        elif self.step==3:
            if self.dashboard.get()=='custom':
                from editor import DashboardEditor
                self.inline_editor=DashboardEditor(self.body,compact=True)
                self.inline_editor.pack(fill='both',expand=True)
                if self.custom_layout:self.inline_editor.set_layout(self.custom_layout)
            else:
                self.text('Présentation sélectionnée : '+next(e[1] for e in EDITIONS if e[0]==self.dashboard.get()))
                if self.dashboard.get() in ('strip_drift','led_segments','purple_drift'):
                    canvas=tk.Canvas(self.body,width=204,height=272,bg='#030609',highlightthickness=0)
                    canvas.pack(anchor='center',pady=8)
                    canvas.bind('<Configure>',lambda e,c=canvas,k=self.dashboard.get():self.paint_theme(c,k))
                    self.text('CH1 à CH4 : −100 % à +100 %, neutre à 0 %. Les jauges CH3/CH4 sont centrées au neutre. Valeurs d’exemple.')
                else:self.action(self.body,'Modifier le placement et les couleurs…',self.choose_custom).pack(fill='x',anchor='w',ipady=10,pady=15)
                option=tk.Checkbutton(self.body,text=tr('USB rapide · 1 ms'),variable=self.fast,bg=BG,fg=INK,
                    selectcolor=PANEL,font=('Segoe UI',11))
                option.pack(anchor='w',pady=12);wrap_to_parent(option,self.body,20)
                self.text('Les menus de la radio sont conservés. Les nouvelles présentations sont expérimentales.')
        elif self.step==4:
            self.render_startup_media()
        elif self.step==5:
            self.text('1. Éteins le véhicule et la radio.\n2. Retire la batterie de la radio.\n3. Branche son câble USB au PC.\n4. Maintiens CH3 + CH4 + Power jusqu’au bip.')
            self.action(self.body,'Le bip a retenti · détecter la radio',self.detect).pack(fill='x',anchor='w',ipady=12,pady=16)
            self.forward.configure(state='normal' if self.identity else 'disabled')
        elif self.step==6:
            self.text('Radio détectée · sauvegarde, transfert et vérification automatiques.\nGarde l’USB branché jusqu’au message de déconnexion.')
            self.label(self.body,'Clique sur « Installer sur la radio », puis accepte la demande Windows.',size=10,bold=True,wraplength=700,justify='left').pack(anchor='w',pady=(0,8))
            self.progress=ttk.Progressbar(self.body,mode='indeterminate');self.progress.pack(fill='x',pady=(0,10))
            self.label(self.body,'Journal de l’installation',size=11,bold=True).pack(anchor='w',pady=(0,6))
            self.log_view=ScrolledText(self.body,height=5,bg='#090f16',fg='#cde8de',
                insertbackground=INK,font=('Consolas',10),wrap='word',state='disabled',relief='flat')
            self.log_view.pack(fill='both',expand=True,pady=(0,12))
            self.log_view.tag_configure('error',foreground='#ff8a8a')
            for line,error in self.log_lines:self.display_log(line,error)
            self.label(self.body,'Un firmware ou un matériel inconnu est refusé.',size=9,color=MUTED,wraplength=700,justify='left').pack(anchor='w')
        else:
            self.text('Le transfert et sa relecture ont réussi.\n1. Laisse l’USB débranché et remets la batterie.\n2. Allume avec Power uniquement.\n3. Vérifie ton dashboard et les commandes.\nPour jouer sur PC, rebranche ensuite l’USB en mode normal.\nLa lecture CH1/CH2 reprend automatiquement dans cette application.')
            self.action(self.body,'Voir la sauvegarde et le compte rendu',lambda:os.startfile(self.job_directory)).pack(fill='x',anchor='w',ipady=10,pady=12)

    def build_gallery(self):
        self.gallery_entries=(*EDITIONS,('custom','Composition personnelle','Place tes jauges et choisis leurs couleurs.',()))
        frame=tk.Frame(self.body,bg=BG);frame.pack(fill='x',pady=(2,0))
        frame.columnconfigure(1,weight=1)
        self.gallery_prev=self.action(frame,'◀',lambda:self.move_gallery(-1),wrap=False)
        self.gallery_next=self.action(frame,'▶',lambda:self.move_gallery(1),wrap=False)
        self.gallery_prev.grid(row=0,column=0,padx=(0,6));self.gallery_next.grid(row=0,column=2,padx=(6,0))
        card=tk.Frame(frame,bg=PANEL,highlightthickness=1,highlightbackground='#385062')
        card.grid(row=0,column=1,sticky='ew');card.columnconfigure(1,weight=1)
        # Keep the whole choice and its navigation in the compact viewport.
        available=self.body_view.canvas.winfo_height()
        height=max(150,min(316,available-85)) if available>1 else 190
        self.gallery_canvas=tk.Canvas(card,width=height*3//4,height=height,bg='#101924',highlightthickness=0,takefocus=True)
        self.gallery_canvas.grid(row=0,column=0,rowspan=3,padx=7,pady=7)
        self.gallery_count=tk.Label(card,bg=PANEL,fg=ACCENT,font=('Segoe UI',9,'bold'),anchor='w')
        self.gallery_count.grid(row=0,column=1,sticky='sw',padx=6)
        self.gallery_title=tk.Label(card,bg=PANEL,fg=INK,font=('Segoe UI',12,'bold'),anchor='w',justify='left')
        self.gallery_title.grid(row=1,column=1,sticky='ew',padx=6)
        self.gallery_detail=tk.Label(card,bg=PANEL,fg=MUTED,font=('Segoe UI',9),anchor='w',justify='left')
        self.gallery_detail.grid(row=2,column=1,sticky='new',padx=6)
        for label in (self.gallery_title,self.gallery_detail):
            label.bind('<Configure>',lambda e:e.widget.configure(wraplength=max(40,e.width-4)))
        self.gallery_canvas.bind('<Configure>',lambda _:self.paint_gallery())
        self.gallery_start=None
        def release(event):
            if self.gallery_start is not None:
                delta=event.x_root-self.gallery_start
                self.gallery_start=None
                if abs(delta)>=28:self.move_gallery(-1 if delta>0 else 1)
        def press(event):
            self.gallery_start=event.x_root
            self.gallery_canvas.focus_set()
        def wheel(event):
            if event.delta:self.move_gallery(-1 if event.delta>0 else 1)
            return 'break'
        for w in (frame,card,self.gallery_canvas,self.gallery_title,self.gallery_detail,self.gallery_count,self.gallery_prev,self.gallery_next):
            w.bind('<Left>',lambda _:self.move_gallery(-1));w.bind('<Right>',lambda _:self.move_gallery(1))
            w.bind('<MouseWheel>',wheel);w.bind('<Shift-MouseWheel>',wheel)
            if w not in (self.gallery_prev,self.gallery_next):
                w.bind('<ButtonPress-1>',press);w.bind('<ButtonRelease-1>',release)
        self.gallery_scroll=ttk.Scrollbar(frame,orient='horizontal',command=self.scroll_gallery)
        self.gallery_scroll.grid(row=1,column=1,sticky='ew',pady=(5,0))
        self.select_dashboard(self.dashboard.get())
        self.gallery_canvas.focus_set()

    def scroll_gallery(self,op,value,*unit):
        entries=self.gallery_entries
        if op=='moveto':self.select_dashboard(entries[min(len(entries)-1,max(0,round(float(value)*len(entries))))][0])
        elif op=='scroll':self.move_gallery(int(value))

    def move_gallery(self,direction):
        keys=[e[0] for e in self.gallery_entries]
        self.select_dashboard(keys[(keys.index(self.dashboard.get())+direction)%len(keys)])
        return 'break'

    def select_dashboard(self,key):
        if self.busy:return
        if self.step!=2 or self.pc_mode:return super().select_dashboard(key)
        keys=[e[0] for e in self.gallery_entries]
        index=keys.index(key)
        self.dashboard.set(key)
        self.gallery_scroll.set(index/len(keys),(index+1)/len(keys))
        _,title,detail,_=self.gallery_entries[index]
        self.gallery_count.configure(text=f'{index+1:02} / {len(keys):02}')
        self.gallery_title.configure(text=tr(title))
        self.gallery_detail.configure(text=tr(detail))
        self.paint_gallery()

    def paint_gallery(self):
        c=self.gallery_canvas
        key=self.dashboard.get()
        if key in ('strip_drift','led_segments','purple_drift'):
            self.paint_theme(c,key);return
        c.delete('all')
        if key!='custom':
            channels=next(e[3] for e in EDITIONS if e[0]==key)
            w,h=c.winfo_width(),c.winfo_height()
            if w<20:return
            for i,ch in enumerate(channels):
                y=round((i+1)*h/(len(channels)+1))
                c.create_text(5,y,text=f'CH{ch}',fill=INK,anchor='w',font=('Segoe UI',-11,'bold'))
                c.create_rectangle(38,y-3,w-27,y+3,fill='#324b65',outline='')
                x=(38+w-27)/2;c.create_line(x,y-4,x,y+4,fill=ACCENT)
                c.create_text(w-4,y,text='0%',fill=MUTED,anchor='e',font=('Segoe UI',-10))
            return
        from dashboard_zones import DEFAULT_LOWER
        layout=self.custom_layout or DEFAULT_LOWER
        w,h=c.winfo_width(),c.winfo_height()
        if w<20:return
        cell=min((w-10)/6,(h-18)/4)
        left=(w-cell*6)/2;top=(h-cell*4)/2
        for i in range(5):
            c.create_line(left,top+i*cell,left+6*cell,top+i*cell,fill='#324b65')
        for i in range(7):
            c.create_line(left+i*cell,top,left+i*cell,top+4*cell,fill='#324b65')
        for item in layout['widgets']:
            x=left+item['col']*cell;y=top+item['row']*cell;col=item['color']
            if item['kind']=='bar':
                c.create_line(x+4,y+cell/2,x+4*cell-4,y+cell/2,width=3,fill=col)
                c.create_line(x+2*cell,y+cell/2-4,x+2*cell,y+cell/2+4,fill=INK)
            elif item['kind']=='semicircle':c.create_arc(x+3,y+3,x+2*cell-3,y+2*cell-3,start=0,extent=180,style='arc',outline=col,width=3)
            else:c.create_text(x+cell/2,y+cell/2,text=f"CH{item['channel']}",fill=col,font=('Segoe UI',-10,'bold'))

    def paint_theme(self,canvas,key):
        from dashboard_fullscreen import paint
        paint(canvas,key)

    def needs_media_chrome(self):
        height=self.root.winfo_height()
        return height>1 and height<=max(460,320*float(self.root.tk.call('tk','scaling')))

    def set_media_chrome(self,compact):
        """Give the preview room on small screens, then restore normal wizard chrome."""
        saved=getattr(self,'_media_chrome',None)
        if bool(saved)==compact:return
        if compact:
            height=self.root.winfo_height()
            px=max(12,min(18,height//31))
            plain=('Segoe UI',-px);bold=(*plain,'bold')
            changes=[(self.brand_label,dict(font=bold)),(self.step_label,dict(font=bold)),
                     (self.language_combo,dict(font=plain,width=10)),
                     (self.forward,dict(font=bold,padx=10,pady=3)),
                     (self.radio_button,dict(font=plain,padx=5,pady=2)),(self.play_button,dict(font=plain,padx=5,pady=2))]
            ttk.Style(self.root).configure('Startup.TButton',font=plain,padding=(5,1))
            changes.append((self.back,dict(style='Startup.TButton')))
            self._media_chrome=[(w,{key:w.cget(key) for key in options}) for w,options in changes]
            for widget,options in changes:widget.configure(**options)
            self.outer.pack_configure(padx=8,pady=5)
            self.title_label.pack_forget();self.game_label.grid_remove()
            self.step_label.grid_configure(pady=(3,3));self.back.pack_configure(ipady=0)
        else:
            for widget,options in saved:widget.configure(**options)
            self._media_chrome=None
            self.outer.pack_configure(padx=16,pady=12)
            self.title_label.pack(before=self.body,fill='x',pady=(0,8));self.game_label.grid()
            self.step_label.grid_configure(pady=(8,3));self.back.pack_configure(ipady=4)

    def render_startup_media(self):
        from startup_panel import StartupPanel
        self.media_panel=StartupPanel(self)
        self.media_panel.pack(fill='both',expand=True)

    def choose_startup_media(self):
        if self.busy or self.media_loading:return
        path=filedialog.askopenfilename(parent=self.root,title=tr('Choisir une photo ou un GIF…'),
            filetypes=[(tr('Photo / GIF'),'*.png *.jpg *.jpeg *.bmp *.gif'),('PNG / JPEG / BMP','*.png *.jpg *.jpeg *.bmp'),('GIF','*.gif')])
        if not path:return
        self.launch_media_conversion(path=path)

    def launch_media_conversion(self,*,path):
        self.media_loading=True;self.render()
        def work():
            try:
                import startup_media
                name,blob=startup_media.read_source(path)
                result=startup_media.from_bytes(blob,name=name)
                self.events.put(('media_ready',(name,blob,result),None))
            except Exception as error:self.events.put(('media_error',str(error),None))
        threading.Thread(target=work,daemon=True).start()

    def use_startup_media(self):
        if self.busy or self.media_loading or not self.media_candidate_valid or not self.media_candidate:return
        self.startup_media=self.media_candidate;self.media_pending=False;self.target=None;self.render()

    def clear_startup_media(self):
        if self.busy or self.media_loading:return
        self.startup_media=None;self.media_source=None;self.media_candidate=None
        self.media_candidate_valid=False;self.media_pending=False;self.target=None;self.render()

    def stop_startup_preview(self):
        if self.preview_after is not None:
            self.root.after_cancel(self.preview_after);self.preview_after=None
        self.preview_images=[];self.preview_canvas=None;self.preview_signature=None

    def resize_startup_preview(self,event):
        if event.widget is not self.preview_canvas:return
        self.start_startup_preview(resizing=True)

    def start_startup_preview(self,*,resizing=False):
        media=self.media_candidate or self.startup_media
        canvas=self.preview_canvas
        if not media or not canvas:return
        w,h=canvas.winfo_width(),canvas.winfo_height()
        scale=min(w/240,h/320,1)
        if scale<0.02:return
        size=(max(1,int(240*scale)),max(1,int(320*scale)))
        signature=(id(media),size)
        if resizing and self.preview_signature==signature:
            canvas.coords('frame',w//2,h//2);return
        if self.preview_after is not None:self.root.after_cancel(self.preview_after);self.preview_after=None
        if self.preview_signature!=signature:
            from PIL import ImageTk,Image
            from startup_media import preview_media
            frames,self.preview_durations=preview_media(media)
            self.preview_images=[ImageTk.PhotoImage(frame.resize(size,Image.Resampling.NEAREST),master=canvas) for frame in frames]
            self.preview_signature=signature
        canvas.delete('frame')
        item=canvas.create_image(w//2,h//2,image=self.preview_images[0],tags='frame')
        def show(index):
            self.preview_after=None
            if canvas is not self.preview_canvas:return
            frame=index%len(self.preview_images)
            canvas.itemconfigure(item,image=self.preview_images[frame])
            if index+1<len(self.preview_images):
                self.preview_after=self.root.after(self.preview_durations[frame],lambda:show(index+1))
        show(0)

    def confirm_version(self):
        self.version_confirmed=True
        if self.source.get():self.step=2
        self.render()

    def select_language(self,value):
        previous=i18n.language()
        self.language_combo.current(0 if previous=='en' else 1)
        if value==previous or self.busy or self.media_loading:return
        selection=tab=None
        if self.inline_editor:
            try:self.custom_layout=self.inline_editor.get_layout()
            except ValueError as error:
                messagebox.showerror(tr('Composition à vérifier'),tr(str(error)),parent=self.root);return
            selection=self.inline_editor.widget_combo.current()
            notebook=getattr(self.inline_editor,'notebook',None)
            if notebook:tab=notebook.index('current')
        status=self.status.source_text
        i18n.set_language(value)
        self.language_combo.current(0 if value=='en' else 1)
        self.back.configure(text=tr('Retour'))
        self.game_status.set(self.game_status.source_text)
        self.root.title(tr('DDF-350 · Personnaliser et jouer')+' · '+p.VERSION.split('-')[0])
        self.render()
        if self.inline_editor and selection is not None and selection>=0:
            self.inline_editor.widget_combo.current(selection);self.inline_editor._select_from_combo(None)
            if tab is not None:self.inline_editor.notebook.select(tab)
        if status and not self.status.get():self.status.set(status)
        if self.tray:self.tray.refresh_language()
        try:i18n.save_language(value)
        except OSError as error:self.status.set(str(error))

    def render_firmware_source(self):
        self.title_label.configure(text=tr('Sélectionner le firmware officiel'))
        self.text('Aucun firmware constructeur n’est inclus dans l’application.\n1. Ouvre la page DumboRC et obtiens la version 2.0.5.\n2. Extrais l’archive sur ton PC.\n3. Sélectionne son fichier DDF.bin ci-dessous.')
        self.download_button=self.action(self.body,'1 · Ouvrir la page officielle DumboRC',self.open_official_download)
        self.download_button.pack(fill='x',anchor='w',ipady=8,pady=(0,10))
        self.firmware_button=self.action(self.body,'2 · Choisir le fichier DDF.bin officiel 2.0.5…',self.browse)
        self.firmware_button.pack(fill='x',anchor='w',ipady=8,pady=(0,10))
        self.text('Fichier vérifié : '+Path(self.source.get()).name if self.source.get() else 'Aucun fichier sélectionné. Seul l’original 2.0.5 exact sera accepté.')
        self.text('Si le téléchargement 2.0.5 est indisponible sur le site, demande-le au fabricant.\nUne autre version ou un fichier déjà modifié sera refusé.')
        self.back.configure(state='normal')
        self.forward.configure(state='normal' if self.source.get() else 'disabled')

    def browse(self):
        super().browse()
        if self.step==1 and self.version_confirmed:self.render()

    def choose_custom(self):
        if self.custom_layout is None:
            from dashboard_zones import DEFAULT_LOWER as DEFAULT
            self.custom_layout=copy.deepcopy(DEFAULT)
        self.dashboard.set('custom')
        self.step=3
        self.render()

    def previous(self):
        if self.busy or self.media_loading:return
        if self.pc_mode:
            self.pc_mode=False
            self.render()
            return
        if self.step==1:
            self.version_confirmed=False;self.render();return
        if self.inline_editor:
            try:self.custom_layout=self.inline_editor.get_layout()
            except ValueError:pass
        self.step=max(1,self.step-1);self.render()

    def next(self):
        if self.busy or self.media_loading:return
        if self.pc_mode:
            self.hide_to_tray()
            return
        if self.step==1 and (not self.version_confirmed or not self.source.get()):return
        if self.step==2 and self.dashboard.get()=='custom':
            self.choose_custom();return
        if self.step==3:
            if self.inline_editor:
                try:self.custom_layout=self.inline_editor.get_layout()
                except ValueError as error:
                    messagebox.showerror(tr('Composition à vérifier'),tr(str(error)),parent=self.root);return
        if self.step==4:
            if self.media_pending:return
            try:
                if not self.source.get():
                    self.browse()
                if not self.source.get():return
                original=p.read_regular_file(self.source.get())
                options={'dashboard':self.dashboard.get(),'usb_1ms':self.fast.get()}
                if self.dashboard.get()=='custom':options['layout']=p.dashboard_custom.current_layout(self.custom_layout)
                if self.startup_media:
                    options['startup_photo' if self.startup_media.kind=='photo' else 'startup_animation']=self.startup_media.asset
                self.target=p.build_patch(original,**options)
            except Exception as error:
                messagebox.showerror(tr('Préparation impossible'),tr(str(error)),parent=self.root);return
        if self.step==5 and not self.identity:return
        if self.step==6:
            self.install();return
        if self.step==7:
            self.game_enabled=True
            self.start_game_reader()
            self.hide_to_tray();return
        self.step+=1;self.render()

    def detect(self):
        if self.busy:return
        self.busy=True;self.forward.configure(state='disabled');self.back.configure(state='disabled')
        self.status.set('Recherche de la radio…')
        def work():
            try:self.events.put(('detected',installer.discover(),None))
            except Exception as error:self.events.put(('detect_error',str(error),None))
        threading.Thread(target=work,daemon=True).start()

    def install(self):
        if self.busy or not self.identity or self.target is None:return
        if self.viewer is not None and not self.viewer.closed:self.viewer.close()
        self.stop_game_reader()
        self.busy=True;self.back.configure(state='disabled');self.forward.configure(state='disabled')
        self.progress.start(20)
        self.status.set('Préparation de l’installation · accepte la demande Windows…')
        self.job_directory=installer.runs_root()/uuid.uuid4().hex
        self.last_phase=None
        self.log_offset=0;self.log_pending=b'';self.log_lines=[]
        if self.log_view:
            self.log_view.configure(state='normal');self.log_view.delete('1.0','end');self.log_view.configure(state='disabled')
        try:
            p._check_local_volume(self.job_directory,'Sauvegarde')
            self.job_directory.mkdir(parents=True,exist_ok=False)
            original=p.read_regular_file(self.source.get())
            p._require_original(original)
            # Give the elevated worker an exact local snapshot, independent of
            # the original download path or the developer's environment.
            p.write_new_output(self.job_directory/'original.bin',original,source=self.source.get())
            with (self.job_directory/'target.bin').open('xb') as f:f.write(self.target)
            with (self.job_directory/'job.json').open('x',encoding='utf-8') as f:
                json.dump({'identity':self.identity,'target_sha256':p.sha256(self.target)},f)
        except Exception as error:
            self.finish_error(str(error));return
        self.log('Fichier du dashboard préparé et vérifié.')
        self.log('Lancement du processus administrateur. Windows peut demander confirmation ; si l’application est déjà administrateur, aucune nouvelle fenêtre n’est nécessaire.')
        def work():
            try:self.events.put(('launched',installer.launch_elevated(self.job_directory),None))
            except Exception as error:self.events.put(('install_error',str(error),None))
        threading.Thread(target=work,daemon=True).start()

    def finish_error(self,message):
        self.busy=False
        if hasattr(self,'progress'):self.progress.stop()
        self.status.set(message)
        self.log(message,error=True)
        self.back.configure(state='normal');self.forward.configure(state='normal')
        if self.game_enabled and self.worker_handle is None:self.start_game_reader()

    def poll(self):
        if self.closed:return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id=None
        try:kind,value,_=self.events.get_nowait()
        except queue.Empty:pass
        else:
            if kind=='detected':
                self.busy=False;self.identity=value
                self.status.set('DDF-350 détectée. Tu peux continuer.')
                self.back.configure(state='normal');self.forward.configure(state='normal')
            elif kind=='detect_error':
                self.busy=False;self.identity=None
                self.status.set(value);self.back.configure(state='normal')
            elif kind=='launched':
                self.worker_handle=value
                self.log('Processus d’installation lancé. Attente de son premier compte rendu…')
            elif kind=='install_error':self.finish_error(value)
            elif kind in ('media_ready','media_error'):
                self.media_loading=False
                if kind!='media_error':
                    name,blob,result=value
                    self.media_source=(name,blob);self.media_candidate=result
                    self.media_candidate_valid=True;self.media_pending=True;self.target=None
                self.render()
                if kind=='media_error':self.status.set(value)
        if self.worker_handle:
            self.read_worker_log()
            try:
                report=json.loads((self.job_directory/'status.json').read_text(encoding='utf-8'))
                self.last_phase=report['phase'];self.status.set(report['message'])
            except (OSError,ValueError):pass
            active=installer.worker_active(self.worker_handle)
            if not active:
                installer.close_process(self.worker_handle);self.worker_handle=None
                if self.last_phase=='done':
                    self.busy=False;self.progress.stop();self.step=7;self.render()
                    if self.game_enabled:self.start_game_reader()
                else:
                    self.finish_error(self.status.get() if self.last_phase=='error' else
                        'Le transfert a été interrompu. Débranche l’USB et garde la radio éteinte. Consulte le dossier de sauvegarde avant de réessayer.')
        self.poll_game_reader()
        self.poll_tray()
        if self.closed:return
        self.poll_id=self.root.after(100,self.poll)

    def start_game_reader(self):
        if self.game_reader is not None and self.game_reader.is_alive():return
        from pc.ddf350_hid import Reader
        self.game_reader=Reader(self.game_events)
        self.game_reader.start()
        self.game_status.set('USB · recherche de la radio · lecture automatique active')

    def stop_game_reader(self):
        if self.game_reader is not None:
            self.game_reader.request_stop()
            self.game_reader=None
        self.game_values=None;self.game_last_data=None

    def poll_game_reader(self):
        for _ in range(128):
            try:kind,value,stamp=self.game_events.get_nowait()
            except queue.Empty:break
            if kind=='data':self.game_values=value;self.game_last_data=stamp
            elif kind in ('disconnected','searching','error'):
                self.game_values=None;self.game_last_data=None
                self.game_status.set('USB · en attente de la radio · reconnexion automatique')
        if self.game_values is not None:
            if time.monotonic()-self.game_last_data<1:
                self.game_status.set(f'USB actif · CH1 : {self.game_values.ch1}    CH2 : {self.game_values.ch2} · lecture automatique')
            else:self.game_status.set('USB connecté · attente de nouvelles données CH1/CH2')
        self.paint_pc_inputs()

    def show_pc_mode(self, *, start_reader=True):
        if self.busy or self.media_loading:return
        if self.inline_editor:
            try:self.custom_layout=self.inline_editor.get_layout()
            except ValueError as error:
                messagebox.showerror(tr('Composition à vérifier'),tr(str(error)),parent=self.root);return
        self.pc_mode=True
        if start_reader:
            self.game_enabled=True
            self.start_game_reader()
        self.render()

    def show_radio_mode(self):
        if self.busy or self.media_loading:return
        self.pc_mode=False
        if self.step==7:
            self.step=1;self.version_confirmed=False;self.identity=None;self.target=None
        # Keep an in-progress editor intact when already on the radio page.
        if self.inline_editor:return
        self.render()

    def render_pc_mode(self):
        self.step_label.configure(text=tr('MODE PC · LECTURE EN DIRECT'))
        self.title_label.configure(text=tr('Activer la télécommande sur PC'))
        self.back.configure(state='normal')
        self.forward.configure(text=tr('Réduire pour jouer'),state='normal')
        self.status.set('Laisse cette application ouverte ou réduite. La lecture recherche la radio et se reconnecte automatiquement.')
        self.text('Allume la radio normalement avec Power, puis branche l’USB.\nLes mouvements CH1 et CH2 apparaissent ci-dessous, sans lancer Python.')
        for channel,title in ((1,'CH1 · Direction'),(2,'CH2 · Accélération / frein')):
            frame=tk.Frame(self.body,bg=PANEL,padx=14,pady=8)
            frame.pack(fill='x',pady=(0,10))
            row=tk.Frame(frame,bg=PANEL);row.pack(fill='x')
            self.label(row,title,size=11,bold=True).pack(side='left')
            number=self.label(row,'—',size=23,color=ACCENT,bold=True);number.pack(side='right')
            canvas=tk.Canvas(frame,height=18,bg=PANEL,highlightthickness=0)
            canvas.pack(fill='x',pady=(3,2))
            canvas.bind('<Configure>',lambda _event:self.paint_pc_inputs())
            self.pc_panels.append((channel,number,canvas))
        import pc_startup
        self.pc_startup_enabled=tk.BooleanVar(master=self.root,value=False)
        try:self.pc_startup_enabled.set(pc_startup.is_enabled())
        except OSError as error:self.status.set(str(error))
        self.startup_check=tk.Checkbutton(self.body,text=tr('Activer automatiquement à l’ouverture de Windows · démarrage réduit'),
            variable=self.pc_startup_enabled,command=self.change_pc_startup,bg=BG,fg=INK,selectcolor=PANEL,
            activebackground=BG,activeforeground=INK,font=('Segoe UI',9),anchor='w')
        self.startup_check.pack(fill='x',pady=(2,4))
        wrap_in_control(self.startup_check)
        self.paint_pc_inputs()

    def change_pc_startup(self):
        import pc_startup
        requested=self.pc_startup_enabled.get()
        try:
            if requested:pc_startup.enable()
            else:pc_startup.disable()
        except (OSError,ValueError) as error:
            self.pc_startup_enabled.set(not requested)
            messagebox.showerror(tr('Démarrage automatique'),tr(str(error)),parent=self.root)
        else:self.status.set('Démarrage Windows activé pour ton compte. L’application démarrera réduite en mode PC.' if requested else 'Démarrage Windows désactivé.')

    def paint_pc_inputs(self):
        fresh=self.game_values is not None and self.game_last_data is not None and time.monotonic()-self.game_last_data<1
        for channel,number,canvas in self.pc_panels:
            value=getattr(self.game_values,f'ch{channel}') if fresh else None
            number.configure(text=tr('—' if value is None else str(value)),fg=ACCENT if fresh else MUTED)
            canvas.delete('all');width=max(2,canvas.winfo_width()-2)
            canvas.create_rectangle(1,5,width,14,fill='#34475c',outline='')
            if value is not None:
                canvas.create_rectangle(1,5,1+(width-1)*value/2047,14,fill=ACCENT,outline='')
            canvas.create_line(width/2,2,width/2,17,fill=INK)

    def poll_tray(self):
        if self.tray:
            active=self.game_values is not None and self.game_last_data is not None and time.monotonic()-self.game_last_data<1
            self.tray.set_connected(active)
        for _ in range(32):
            try:kind,value=self.tray_events.get_nowait()
            except queue.Empty:break
            if kind=='open':self.show_from_tray()
            elif kind=='radio':
                self.show_radio_mode()
                self.show_from_tray()
            elif kind=='quit':
                self.close()
                if self.closed:return
            elif kind=='tray_ready':
                if value and self.hide_requested:self.hide_to_tray()
                elif not value:self.status.set('Icône Windows indisponible. La fenêtre reste accessible dans la barre des tâches.')
            elif kind=='tray_error':
                self.status.set('Synchronisation : '+str(value))
                if not self.tray or not self.tray.available:self.show_from_tray()

    def hide_to_tray(self):
        self.hide_requested=True
        if self.tray and self.tray.available:self.root.withdraw()
        else:self.root.iconify()

    def show_from_tray(self):
        self.hide_requested=False
        self.root.deiconify();self.root.lift()

    def on_minimize(self,event):
        if event.widget is self.root and self.root.state()=='iconic' and self.tray and self.tray.available:
            self.root.after_idle(self.hide_to_tray)

    def window_close(self):
        if self.busy:
            messagebox.showinfo(tr('Installation en cours'),tr('Attends le message de déconnexion avant de fermer.'),parent=self.root)
        elif self.tray and self.tray.available:self.hide_to_tray()
        else:self.close()

    def display_log(self,line,error=False):
        line=tr(line)
        if self.log_view and self.log_view.winfo_exists():
            self.log_view.configure(state='normal')
            self.log_view.insert('end',line+'\n','error' if error else '')
            self.log_view.see('end');self.log_view.configure(state='disabled')

    def log(self,message,error=False):
        line=datetime.now().strftime('%H:%M:%S')+'  '+str(message)
        self.log_lines.append((line,error));self.display_log(line,error)
        if self.job_directory:
            try:installer.append_log(self.job_directory,'error' if error else 'interface',message,filename='interface.jsonl')
            except (OSError,ValueError):pass

    def read_worker_log(self):
        try:
            with (self.job_directory/'journal.jsonl').open('rb') as f:
                f.seek(self.log_offset);data=f.read();self.log_offset=f.tell()
        except OSError:return
        records=(self.log_pending+data).split(b'\n');self.log_pending=records.pop()
        for record in records:
            try:
                entry=json.loads(record.decode('utf-8'))
                line=entry['time'][11:19]+'  '+entry['message']
                error=entry['phase'] in ('error','error_unplug','diagnostic')
                self.log_lines.append((line,error));self.display_log(line,error)
            except (ValueError,KeyError,TypeError):
                self.log('Ligne du journal illisible.',error=True)

    def close(self):
        if self.closed:return
        if self.busy:
            messagebox.showinfo(tr('Installation en cours'),tr('Attends le message de déconnexion et débranche l’USB avant de fermer.'),parent=self.root)
            return
        self.stop_game_reader()
        self.stop_startup_preview()
        if self.tray:self.tray.close()
        super().close()
