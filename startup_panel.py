"""Step 4 of the portable wizard. All editing controls share one viewport."""
import tkinter as tk
from tkinter import font as tkfont, messagebox

from app import BG, PANEL, INK, MUTED, ACCENT
from i18n import tr


class StartupPanel(tk.Frame):
    def __init__(self,wizard):
        super().__init__(wizard.body,bg=BG)
        self.ui=wizard
        height=wizard.root.winfo_height()
        self.px=max(12,min(20,(height if height>1 else 480)//31,
                           round(float(self.tk.call('tk','scaling'))*10)))
        self.font=('Segoe UI',-self.px)
        self.columnconfigure(0,weight=1)
        self.rowconfigure(1,weight=1)
        self.notice=None
        media=wizard.media_candidate or wizard.startup_media
        editing=bool(media or wizard.media_source or wizard.media_loading)
        from startup_media import GIF_HELP
        choices=tk.Frame(self,bg=BG)
        choices.grid(row=0,column=0,sticky='ew',pady=(0,4))
        for col in (0,1):choices.columnconfigure(col,weight=1,uniform='choices')
        narrow=1<wizard.root.winfo_width()<580
        self.original=self.button(choices,'Original' if narrow else 'Garder le démarrage d’origine',wizard.clear_startup_media,active=not editing)
        self.original.grid(row=0,column=0,sticky='ew',padx=(0,3))
        self.choose=self.button(choices,'Photo / GIF…' if narrow else 'Choisir une photo ou un GIF…',
                                wizard.choose_startup_media,active=editing)
        self.choose.grid(row=0,column=1,sticky='ew',padx=(3,0))
        wizard.media_choose_button=self.choose
        tk.Label(choices,text=tr(GIF_HELP),bg=BG,fg=INK,font=('Segoe UI',-max(11,self.px-2)),
                 wraplength=max(300,wizard.root.winfo_width()-58),justify='left',anchor='w').grid(row=1,column=0,columnspan=2,sticky='ew',pady=(2,0))
        if not editing:
            tk.Label(self,text=tr('Photo centrée à 80 % · PNG, JPEG ou BMP.')+'\n'+tr('GIF facultatif et expérimental : un blocage reste possible.'),
                     bg=BG,fg=MUTED,font=self.font,wraplength=max(300,wizard.root.winfo_width()-58),anchor='nw',justify='left').grid(row=1,column=0,sticky='nsew')
            return

        workspace=tk.Frame(self,bg=PANEL)
        workspace.grid(row=1,column=0,sticky='nsew')
        workspace.rowconfigure(0,weight=1)
        workspace.columnconfigure(0,weight=2);workspace.columnconfigure(1,weight=3)
        # Both columns take a share of the available size. A 1px canvas request
        # lets its image scale to the free area instead of growing the window.
        preview=tk.Frame(workspace,bg='#0b141e');preview.grid(row=0,column=0,sticky='nsew',padx=(0,4))
        preview.columnconfigure(0,weight=1);preview.rowconfigure(0,weight=1)
        wizard.preview_canvas=tk.Canvas(preview,bg='#0b141e',highlightthickness=0,width=1,height=1)
        wizard.preview_canvas.grid(row=0,column=0,sticky='nsew')
        if media:
            wizard.preview_canvas.bind('<Configure>',wizard.resize_startup_preview)
            if media.kind=='gif':
                self.replay=self.button(preview,'Rejouer',wizard.start_startup_preview)
                self.replay.grid(row=1,column=0,sticky='ew')
        editor=tk.Frame(workspace,bg=PANEL);editor.grid(row=0,column=1,sticky='nsew',padx=6,pady=3)
        for col in (0,1):editor.columnconfigure(col,weight=1,uniform='setting')
        if media:
            # The full filename and conversion information are accessible from
            # this button even when a long filename has been shortened to fit.
            self.file=self.button(editor,'',lambda:self.details(media))
            self.file.configure(anchor='w',fg=ACCENT,width=1)
            self.file.grid(row=0,column=0,columnspan=2,sticky='ew')
            self.file.bind('<Configure>',lambda event:self.fit_name(event,media.name))
        if media:
            i=media.info
            stats=('192 × 256 · RGB565' if media.kind=='photo' else
                   f"{i['frames']} {tr('images')} · {i['duration_ms']/1000:g} s · {tr('16 couleurs')}")
            tk.Label(editor,text=stats,bg=PANEL,fg=MUTED,font=('Segoe UI',-max(11,self.px-1)),
                     anchor='w').grid(row=3,column=0,columnspan=2,sticky='ew',pady=(2,1))
        if wizard.media_loading:
            action='Conversion du média…';command=None
            for btn in (self.original,self.choose,wizard.back,wizard.forward):btn.configure(state='disabled')
        elif wizard.media_pending:
            action='Utiliser ce rendu'
            command=wizard.use_startup_media if wizard.media_candidate_valid else None
            wizard.forward.configure(state='disabled')
        else:
            action='Rendu sélectionné';command=None
        self.apply=self.button(editor,action,command,active=bool(command))
        self.apply.grid(row=4,column=0,columnspan=2,sticky='ew',pady=(3,0))
        if command is None:self.apply.configure(state='disabled',disabledforeground=MUTED)

    def button(self,parent,label,command,*,active=False):
        return tk.Button(parent,text=tr(label),command=command,font=self.font,relief='flat',
            bg='#22404b' if active else '#233343',fg=INK,activebackground=ACCENT,activeforeground=BG,
            highlightthickness=1,highlightbackground=ACCENT if active else '#35495c',padx=4,pady=3)

    def fit_name(self,event,name):
        font=tkfont.Font(root=self,font=self.font)
        room=max(0,event.width-18)
        if font.measure(name)>room:
            prefix=name
            while prefix and font.measure(prefix+'…')>room:prefix=prefix[:-1]
            name=prefix+'…'
        self.file.configure(text=name)

    def details(self,media):
        i=media.info
        from startup_media import GIF_HELP
        lines=[media.name, f"{i['width']} × {i['height']}",
               tr('Photo centrée à 80 % · PNG, JPEG ou BMP.') if media.kind=='photo' else tr(GIF_HELP)]
        messagebox.showinfo(tr('Détails du média'),'\n'.join(lines),parent=self.ui.root)

    def show_notice(self,value):
        if self.notice:self.notice.destroy();self.notice=None
        if value:
            self.notice=self.button(self,'Voir le message…',lambda:messagebox.showinfo(
                tr('Écran de démarrage'),self.ui.status.get(),parent=self.ui.root))
            self.notice.grid(row=2,column=0,sticky='ew',pady=(2,0))
