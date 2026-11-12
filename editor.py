"""Visual JSON dashboard editor. No firmware, USB, radio or build operations.

DashboardEditor(master, layout=None, onchange=None) is a normal tk.Frame.
onchange receives a detached, canonical layout dictionary after an accepted edit.
The firmware backend's validator is imported only when a layout is validated.
"""
from __future__ import annotations

import copy
import json
import math
import re
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
import i18n
from i18n import tr
from ui_layout import ScrollArea,wrap_to_parent,wrap_in_control


SCREEN_WIDTH, SCREEN_HEIGHT = 240, 320
ZONE_X, ZONE_Y, ZONE_WIDTH, ZONE_HEIGHT = 20, 200, 215, 100
COLS, ROWS = 6, 4
SPANS = {"bar": (4, 1), "semicircle": (2, 2), 'number':(2,2),'battery':(3,2)}
KIND_NAMES = {"bar": "Barre", "semicircle": "Demi-cercle",'number':'Chiffres','battery':'Pile'}
UI_BG, UI_PANEL, UI_TEXT, UI_MUTED = "#101924", "#1b2939", "#eff5fc", "#a6b5c8"
ACCENT, ERROR = "#55dfd0", "#ff717a"
THEMES = {
    "Bleu drift": ("#162d46", ("#55b8f0", "#69d7d0", "#a794f4", "#f1bc61", "#7cc99c", "#ed8db1")),
    "Rouge nuit": ("#241b25", ("#ff7b7b", "#ffad76", "#ef83bf", "#c6a1ff", "#f2ce83", "#81c9d8")),
    "Menthe": ("#132b29", ("#79e0b4", "#7dcbd8", "#c6da85", "#b3b5ed", "#edae82", "#e6c279")),
}
DEFAULT_LAYOUT = {
    "schema": 1,
    "background": "#162d46",
    "widgets": [
        {"id": "g1", "channel": 1, "kind": "bar", "col": 0, "row": 0, "color": "#55b8f0"},
        {"id": "g2", "channel": 2, "kind": "bar", "col": 0, "row": 1, "color": "#69d7d0"},
        {"id": "g5", "channel": 5, "kind": "bar", "col": 0, "row": 2, "color": "#7cc99c"},
        {"id": "g6", "channel": 6, "kind": "bar", "col": 0, "row": 3, "color": "#ed8db1"},
        {"id": "g3", "channel": 3, "kind": "semicircle", "col": 4, "row": 0, "color": "#a794f4"},
        {"id": "g4", "channel": 4, "kind": "semicircle", "col": 4, "row": 2, "color": "#f1bc61"},
    ],
}


def _fallback_validate(layout):
    """UI-only fallback while the optional firmware backend is unavailable."""
    if not isinstance(layout, dict) or set(layout) != {"schema", "background", "widgets"}:
        raise ValueError("Le fichier doit contenir schema, background et widgets.")
    if type(layout["schema"]) is not int or layout["schema"] != 1:
        raise ValueError("Format de disposition non pris en charge.")
    color_pattern = re.compile(r"#[0-9a-fA-F]{6}\Z")
    if not isinstance(layout["background"], str) or not color_pattern.fullmatch(layout["background"]):
        raise ValueError("La couleur du fond doit être au format #RRGGBB.")
    widgets = layout["widgets"]
    if not isinstance(widgets, list) or not 1 <= len(widgets) <= 6:
        raise ValueError("La disposition doit contenir entre une et six jauges.")
    occupied, ids, channels, result = set(), set(), set(), []
    for widget in widgets:
        if not isinstance(widget, dict) or set(widget) != {"id", "channel", "kind", "col", "row", "color"}:
            raise ValueError("Une jauge contient des champs manquants ou inconnus.")
        identifier = widget["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", identifier) or identifier in ids:
            raise ValueError("Chaque jauge doit avoir un identifiant unique valide.")
        channel = widget["channel"]
        if type(channel) is not int or not 1 <= channel <= 6 or channel in channels:
            raise ValueError("Chaque voie CH1 à CH6 ne peut apparaître qu'une fois.")
        kind = widget["kind"]
        if not isinstance(kind, str) or kind not in SPANS:
            raise ValueError("Type de jauge inconnu.")
        col, row = widget["col"], widget["row"]
        width, height = SPANS[kind]
        if type(col) is not int or type(row) is not int or col < 0 or row < 0 or col + width > COLS or row + height > ROWS:
            raise ValueError("La jauge dépasse la zone modifiable.")
        cells = {(x, y) for x in range(col, col + width) for y in range(row, row + height)}
        if cells & occupied:
            raise ValueError("Deux jauges se chevauchent.")
        color = widget["color"]
        if not isinstance(color, str) or not color_pattern.fullmatch(color):
            raise ValueError("La couleur d'une jauge doit être au format #RRGGBB.")
        occupied |= cells
        ids.add(identifier)
        channels.add(channel)
        result.append({**widget, "color": color.lower()})
    return {"schema": 1, "background": layout["background"].lower(),
            "widgets": sorted(result, key=lambda item: (item["row"], item["col"], item["id"]))}


def validate_editor_layout(layout):
    """Use the canonical backend contract when present; never import a flasher."""
    # The UI validation supplies French explanations; the backend remains the
    # authority for every accepted layout when it is available.
    if type(layout) is dict and layout.get('schema') in (6,12):
        from dashboard_custom import validate_layout
        return copy.deepcopy(validate_layout(layout))
    candidate = _fallback_validate(copy.deepcopy(layout))
    try:
        from dashboard_custom import validate_layout
    except ModuleNotFoundError as error:
        if error.name != "dashboard_custom":
            raise
        return candidate
    return copy.deepcopy(validate_layout(candidate))


def widget_bounds(widget):
    """Integer pixel bounds, matching floor(col * 215 / 6) in the backend."""
    if 'zone' in widget:
        from dashboard_zones import rectangle
        x,y,w,h=rectangle(widget)
        return 20+x,30+y,20+x+w,30+y+h
    width, height = SPANS[widget["kind"]]
    left = ZONE_X + widget["col"] * ZONE_WIDTH // COLS
    right = ZONE_X + (widget["col"] + width) * ZONE_WIDTH // COLS
    top = ZONE_Y + widget["row"] * ZONE_HEIGHT // ROWS
    return left, top, right, top + height * ZONE_HEIGHT // ROWS


def track_color(color, background):
    foreground = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    behind = [int(background[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{(front + 3 * back) // 4:02x}" for front, back in zip(foreground, behind))


def _widget_parts(widget):
    try:
        from dashboard_custom import widget_parts
    except ModuleNotFoundError as error:
        if error.name != "dashboard_custom":
            raise
        left, top, right, bottom = widget_bounds(widget)
        width = right - left
        if widget["kind"] == "bar":
            return {"gauge": (30, 8, width - 78, 8), "title": (0, 4, 25, 16),
                    "value": (width - 40, 4, 40, 16), "text_align": {"title": "left", "value": "right"}}
        return {"gauge": ((width - 68) // 2, 0, 68, 68),
                "title": ((width - 40) // 2, 14, 40, 16),
                "value": ((width - 40) // 2, 33, 40, 16),
                "text_align": {"title": "center", "value": "center"}}
    return widget_parts(widget)


class DashboardEditor(tk.Frame):
    def __init__(self, master, layout=None, onchange=None, compact=False, **kwargs):
        kwargs.setdefault("bg", UI_BG)
        super().__init__(master, **kwargs)
        self.onchange = onchange
        self.compact = compact
        self._layout = self._import_layout(DEFAULT_LAYOUT if layout is None else layout)
        self._selected = self._layout["widgets"][0]["id"]
        self._drag = None
        self._proposal = None
        self._proposal_error = None
        self._widget_ids = []
        self.scale = 1.8
        self.origin = (12, 12)
        self.status = i18n.StringVar(master=self,value="Choisis une jauge, puis glisse-la sur la grille.")
        self.channel = tk.StringVar(master=self)
        self.kind = tk.StringVar(master=self)
        self.theme = tk.StringVar(master=self,value=tr("Bleu drift"))
        self.selection = tk.StringVar(master=self)
        self.minimal_header=tk.BooleanVar(master=self,value=False)
        self._build()
        self._sync_controls()
        self.redraw()

    def get_layout(self):
        """Return a detached canonical dictionary, or raise on invalid layout."""
        return validate_editor_layout(self._layout)

    @staticmethod
    def _import_layout(layout):
        if type(layout) is dict and type(layout.get('schema')) is int and layout['schema'] in (10,11):
            from dashboard_custom import validate_layout
            layout={**validate_layout(layout),'schema':6 if layout['schema']==10 else 2}
        if type(layout) is dict and layout.get('schema')==2:
            from dashboard_zones import validate
            old=validate(layout)
            bottom=[w for w in old['widgets'] if w['zone']=='B']
            if not bottom:raise ValueError(tr('Cette ancienne composition ne contient aucun bloc dans B.'))
            return validate_editor_layout({**old,'schema':6,'widgets':bottom})
        return validate_editor_layout(layout)

    def set_layout(self, layout):
        """Atomically replace the layout; rejected imports leave it untouched."""
        canonical = self._import_layout(layout)
        self._drag = self._proposal = None
        self._proposal_error = None
        self._commit(canonical, "Partie B importée. Le haut reste d’origine." if layout["schema"]==2 else "Disposition chargée.")

    def _label(self, parent, text, *, size=10, color=UI_TEXT, bold=False, **kwargs):
        label=tk.Label(parent, text=tr(text), bg=parent.cget("bg"), fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"),wraplength=200, **kwargs)
        return wrap_to_parent(label,parent,16)

    def _button(self,parent,**kwargs):
        kwargs.setdefault('bg',UI_PANEL);kwargs.setdefault('fg',UI_TEXT)
        kwargs.setdefault('activebackground',ACCENT);kwargs.setdefault('activeforeground',UI_BG)
        kwargs.setdefault('font',('Segoe UI',9));kwargs.setdefault('relief','flat')
        kwargs.setdefault('padx',6);kwargs.setdefault('pady',5);kwargs.setdefault('wraplength',180)
        return wrap_in_control(tk.Button(parent,**kwargs))

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1,weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=UI_BG)
        if not self.compact:
            header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 8))
        self._label(header, "Personnaliser le dashboard", size=18, bold=True).pack(anchor="w")
        self._label(header, "Personnalise la grille du bas et le style du haut.", color=UI_MUTED).pack(anchor="w", pady=(4, 0))

        preview = tk.Frame(self, bg=UI_BG)
        preview.grid(row=1, column=0, sticky="nsew", padx=(16, 10))
        self._label(preview, "ÉCRAN 240 × 320 · APERÇU SCHÉMATIQUE", size=9, color=UI_MUTED).pack(pady=(0, 6))
        self.canvas = tk.Canvas(preview, width=280 if self.compact else 456, height=320 if self.compact else 600, bg=UI_BG,
                                highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        for sequence, dx, dy in (("<Left>", -1, 0), ("<Right>", 1, 0), ("<Up>", 0, -1), ("<Down>", 0, 1)):
            self.canvas.bind(sequence, lambda event, x=dx, y=dy: self._key_move(x, y))
        self.canvas.bind("<Delete>", lambda _event: self._key_delete())
        self.canvas.bind("<Escape>", self._cancel_drag)

        panel = tk.Frame(self, bg=UI_PANEL, padx=16, pady=10)
        panel.grid(row=1, column=1, sticky="nsew", padx=(0, 8))
        if self.compact:
            notebook = ttk.Notebook(panel)
            notebook.pack(fill="both", expand=True)
            gauge_area=ScrollArea(notebook,bg=UI_PANEL,width=210)
            style_area=ScrollArea(notebook,bg=UI_PANEL,width=210)
            blocks_area=ScrollArea(notebook,bg=UI_PANEL,width=210)
            # Keep the button column at a stable width: at 150% scaling in a
            # 640px window it otherwise alternates between 227px and 252px
            # high as the scrollbar repeatedly appears and disappears.
            blocks_area.columnconfigure(1,minsize=blocks_area.bar.winfo_reqwidth())
            gauge_panel=gauge_area.content;style_panel=style_area.content;blocks_panel=blocks_area.content
            for content in (gauge_panel,style_panel,blocks_panel):content.configure(padx=6,pady=4)
            notebook.add(gauge_area, text=tr("Bloc"))
            notebook.add(blocks_area,text=tr('Ajouter'))
            notebook.add(style_area, text=tr("Style"))
            self.notebook=notebook;self.blocks_panel=blocks_panel;self.style_panel=style_panel
            panel = gauge_panel
        self._label(panel, "Jauge sélectionnée", size=12, bold=True).pack(anchor="w")
        self.widget_combo = ttk.Combobox(panel, textvariable=self.selection, state="readonly", width=1)
        self.widget_combo.pack(fill="x", pady=(4, 6))
        self.widget_combo.bind("<<ComboboxSelected>>", self._select_from_combo)
        self._label(panel, "Voie").pack(anchor="w")
        self.channel_combo = ttk.Combobox(panel, textvariable=self.channel, values=[f"CH{i}" for i in range(1, 7)], state="readonly",width=1)
        self.channel_combo.pack(fill="x", pady=(2, 5))
        self.channel_combo.bind("<<ComboboxSelected>>", self._change_channel)
        self._label(panel, "Forme").pack(anchor="w")
        self.kind_combo = ttk.Combobox(panel, textvariable=self.kind, values=[tr(name) for name in KIND_NAMES.values()], state="readonly",width=1)
        self.kind_combo.pack(fill="x", pady=(2, 5))
        self.kind_combo.bind("<<ComboboxSelected>>", self._change_kind)
        self.color_button = tk.Button(panel, text=tr("Couleur de la jauge"), command=self.choose_widget_color,
                                      relief="flat", padx=10, pady=6)
        self.color_button.pack(fill="x", pady=(0, 5))
        wrap_to_parent(self.color_button,panel,16)
        arrows = tk.Frame(panel, bg=UI_PANEL)
        arrows.pack(pady=4,fill='x')
        for text, col, row, dx, dy in (("←", 0, 0, -1, 0), ("↑", 1, 0, 0, -1), ("↓", 2, 0, 0, 1), ("→", 3, 0, 1, 0)):
            arrows.columnconfigure(col,weight=1,uniform='arrow')
            self._button(arrows,text=tr(text),width=2,command=lambda x=dx,y=dy:self.move_selected(x,y)).grid(column=col,row=row,padx=1,pady=2,sticky='ew')
        self._button(panel, text=tr("Supprimer cette jauge"), command=self.delete_selected).pack(fill="x", pady=(3, 7))
        if self.compact:
            panel = blocks_panel
        self._label(panel,'Grille B · jauges du bas',color=UI_MUTED).pack(anchor='w')
        self._label(panel, "Ajouter", size=12, bold=True).pack(anchor="w")
        add = tk.Frame(panel, bg=UI_PANEL)
        add.pack(fill="x", pady=(4, 7))
        self._button(add, text=tr("Barre"), command=lambda: self.add_widget("bar")).pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._button(add, text=tr("Demi-cercle"), command=lambda: self.add_widget("semicircle")).pack(side="left", expand=True, fill="x")
        extra=tk.Frame(panel,bg=UI_PANEL);extra.pack(fill='x',pady=(0,4))
        self._button(extra,text=tr('Chiffres'),command=lambda:self.add_widget('number')).pack(side='left',fill='x',expand=True)
        self._button(extra,text=tr('Pile'),command=lambda:self.add_widget('battery')).pack(side='left',fill='x',expand=True)
        if self.compact:panel=style_panel
        self._label(panel, "Fond du dashboard", size=12, bold=True).pack(anchor="w")
        theme_combo = ttk.Combobox(panel, textvariable=self.theme, values=[tr(name) for name in THEMES], state="readonly",width=1)
        theme_combo.pack(fill="x", pady=(4, 4))
        theme_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_theme(self.theme.get()))
        self._button(panel, text=tr("Couleur du fond entier…"), command=self.choose_background).pack(fill="x", pady=(0, 3))
        self._button(panel,text=tr("Photo de fond…"),command=self.choose_wallpaper).pack(fill="x",pady=(0,3))
        self.header_check=ttk.Checkbutton(panel,text=tr("Haut : pile seule"),variable=self.minimal_header,command=self.change_header)
        self.header_check.pack(anchor="w",pady=(0,3))
        self._button(panel,text=tr("Fond par défaut"),command=self.stock_background).pack(fill="x",pady=(0,6))
        ttk.Separator(panel).pack(fill="x", pady=8)
        self._button(panel, text=tr("Importer une disposition JSON"), command=self.import_json).pack(fill="x", pady=(0, 4))
        self._button(panel, text=tr("Exporter la disposition JSON"), command=self.export_json).pack(fill="x")
        self.status_label = tk.Label(self, textvariable=self.status, bg=UI_BG, fg=UI_MUTED,
                                     font=("Segoe UI", 10), anchor="w", justify="left", wraplength=760)
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(3, 4) if self.compact else (10, 14))
        if self.compact:
            self.status_label.configure(wraplength=620, font=("Segoe UI",9))
        wrap_to_parent(self.status_label,self,24)

    def _selected_widget(self):
        return next((widget for widget in self._layout["widgets"] if widget["id"] == self._selected), None)

    def _sync_controls(self):
        widgets = self._layout["widgets"]
        self.minimal_header.set(self._layout.get('header')=='battery_only')
        if self._layout['schema']==12:
            self.theme.set(tr('Photo') if self._layout['wallpaper'] else
                           tr(next((name for name,(color,_) in THEMES.items() if color==self._layout['background']),'Couleur unie')))
        else:self.theme.set(tr(next((name for name,(color,_) in THEMES.items() if color==self._layout['background']),'Bleu drift')))
        self._widget_ids = [widget["id"] for widget in widgets]
        self.widget_combo.configure(values=[f"{widget.get('zone','B')} · "+('BAT' if widget['channel']==0 else f"CH{widget['channel']}") for widget in widgets])
        if self._selected not in self._widget_ids:
            self._selected = self._widget_ids[0]
        widget = self._selected_widget()
        self.widget_combo.current(self._widget_ids.index(self._selected))
        self.channel.set('BAT' if widget['channel']==0 else f"CH{widget['channel']}")
        self.channel_combo.configure(state='disabled' if widget['kind']=='battery' else 'readonly')
        self.kind_combo.configure(values=[tr(KIND_NAMES[k]) for k in (('battery',) if widget['kind']=='battery' else ('bar','semicircle','number') if self._layout['schema'] in (6,12) else ('bar','semicircle'))])
        self.kind.set(tr(KIND_NAMES[widget["kind"]]))
        self.color_button.configure(bg=widget["color"], fg="#101924", activebackground=widget["color"])

    def _message(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(fg=ERROR if error else UI_MUTED)

    def _commit(self, candidate, message):
        canonical = validate_editor_layout(candidate)
        changed = canonical != self._layout
        self._layout = canonical
        self._sync_controls()
        self.redraw()
        self._message(message)
        if changed and self.onchange is not None:
            self.onchange(copy.deepcopy(canonical))

    def _attempt(self, candidate, message):
        try:
            canonical = validate_editor_layout(candidate)
        except (ValueError, TypeError) as error:
            self._sync_controls()
            self.redraw()
            self._message(f"Modification refusée : {error}", True)
            return False
        self._commit(canonical, message)
        return True

    def _edited(self, **changes):
        candidate = copy.deepcopy(self._layout)
        for widget in candidate["widgets"]:
            if widget["id"] == self._selected:
                widget.update(changes)
        return candidate

    def _select_from_combo(self, _event):
        index = self.widget_combo.current()
        if 0 <= index < len(self._widget_ids):
            self._selected = self._widget_ids[index]
            self._sync_controls()
            self.redraw()

    def _change_channel(self, _event):
        value = self.channel.get()
        if re.fullmatch(r"CH[1-6]", value):
            self._attempt(self._edited(channel=int(value[2:])), "Voie modifiée.")

    def _change_kind(self, _event):
        kind = next((key for key, name in KIND_NAMES.items() if tr(name) == self.kind.get()), None)
        if kind is not None:
            self._attempt(self._edited(kind=kind), "Forme modifiée.")

    def choose_widget_color(self):
        widget = self._selected_widget()
        color = colorchooser.askcolor(widget["color"], title=tr("Couleur de la jauge"), parent=self.winfo_toplevel())[1]
        if color:
            self._attempt(self._edited(color=color), "Couleur de la jauge modifiée.")

    def full_background(self,photo=None):
        candidate=copy.deepcopy(self._layout)
        candidate.update(schema=12,wallpaper=photo)
        for widget in candidate['widgets']:widget['zone']='B'
        return candidate

    def change_header(self):
        candidate=self.full_background(self._layout.get('wallpaper'))
        if self.minimal_header.get():candidate['header']='battery_only'
        else:candidate.pop('header',None)
        self._attempt(candidate,'Haut du dashboard modifié.')

    def choose_wallpaper(self):
        path=filedialog.askopenfilename(parent=self.winfo_toplevel(),title=tr('Photo de fond…'),
            filetypes=[(tr('Photo'),'*.png *.jpg *.jpeg *.bmp *.webp')])
        if not path:return
        try:
            from startup_media import read_source
            from dashboard_wallpaper import convert
            _,data=read_source(path)
            self._commit(self.full_background(convert(data)),'Photo appliquée à tout le dashboard.')
        except (ValueError,OSError) as error:
            messagebox.showerror(tr('Photo de fond…'),tr(str(error)),parent=self.winfo_toplevel())

    def stock_background(self):
        if self._layout['schema']!=12:return
        candidate=copy.deepcopy(self._layout);candidate.pop('wallpaper');candidate.pop('header',None);candidate['schema']=6
        from dashboard_zones import DEFAULT_LOWER
        candidate['background']=DEFAULT_LOWER['background']
        self._attempt(candidate,'Fond par défaut rétabli.')

    def choose_background(self):
        color = colorchooser.askcolor(self._layout["background"], title=tr("Couleur du fond entier…"), parent=self.winfo_toplevel())[1]
        if color:
            candidate = self.full_background()
            candidate["background"] = color
            self._attempt(candidate, "Couleur appliquée à tout le dashboard.")

    def apply_theme(self, name):
        name=next((key for key in THEMES if tr(key)==name),name)
        background, palette = THEMES[name]
        candidate = self.full_background()
        candidate["background"] = background
        for widget in candidate["widgets"]:
            widget["color"] = palette[widget["channel"] - 1] if widget['channel'] else '#32eb5a'
        self.theme.set(tr(name))
        self._attempt(candidate, "Couleurs appliquées à tout le dashboard.")

    def move_selected(self, dx, dy):
        widget = self._selected_widget()
        return self._attempt(self._edited(col=widget["col"] + dx, row=widget["row"] + dy), "Jauge déplacée.")

    def _key_move(self, dx, dy):
        self.move_selected(dx, dy)
        return "break"

    def _key_delete(self):
        self.delete_selected()
        return "break"

    def delete_selected(self):
        if len(self._layout["widgets"]) == 1:
            self._message("Garde au moins une jauge. Tu peux changer sa forme ou sa voie.", True)
            return False
        candidate = copy.deepcopy(self._layout)
        candidate["widgets"] = [widget for widget in candidate["widgets"] if widget["id"] != self._selected]
        return self._attempt(candidate, "Jauge supprimée.")

    def add_widget(self, kind):
        if kind not in SPANS:
            raise ValueError("Type de jauge inconnu.")
        used = {widget["channel"] for widget in self._layout["widgets"]}
        channel = (0 if 0 not in used else None) if kind=='battery' else next((value for value in range(1, 7) if value not in used), None)
        if channel is None:
            self._message("Les six voies sont déjà présentes. Supprime une jauge pour la remplacer.", True)
            return False
        ids = {widget["id"] for widget in self._layout["widgets"]}
        number = 1
        while f"g{number}" in ids:
            number += 1
        identifier = f"g{number}"
        for row in range(ROWS):
            for col in range(COLS):
                candidate = copy.deepcopy(self._layout)
                theme=next((k for k in THEMES if tr(k)==self.theme.get()),'Bleu drift')
                item={"id":identifier,"channel":channel,"kind":kind,'col':col,'row':row,'color':THEMES[theme][1][channel-1] if channel else '#32eb5a'}
                if kind in ('number','battery') and candidate['schema']==1:
                    candidate['schema']=6
                    for widget in candidate['widgets']:widget['zone']='B'
                if candidate['schema'] in (6,12):item['zone']='B'
                candidate["widgets"].append(item)
                try:
                    canonical = validate_editor_layout(candidate)
                except (ValueError, TypeError):
                    continue
                self._selected = identifier
                self._commit(canonical, f"CH{channel} ajouté. Tu peux maintenant le déplacer.")
                return True
        self._message("Pas assez de place pour cette forme. Déplace ou supprime une autre jauge.", True)
        return False

    def import_json(self):
        filename = filedialog.askopenfilename(parent=self.winfo_toplevel(), title=tr("Importer une disposition"), filetypes=[(tr("Disposition JSON"), "*.json")])
        if not filename:
            return
        try:
            # Reuse the application's bounded regular-file reader and fixed
            # local volume restriction. A radio's boot volume is never opened.
            from patch_firmware import read_layout_file
            candidate = read_layout_file(filename)
            self.set_layout(candidate)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            self._message("Import refusé : la disposition actuelle est conservée.", True)
            messagebox.showerror(tr("Disposition non chargée"), tr(str(error)), parent=self.winfo_toplevel())

    def export_json(self):
        filename = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title=tr("Exporter la disposition"), defaultextension=".json", filetypes=[(tr("Disposition JSON"), "*.json")])
        if not filename:
            return
        try:
            from patch_firmware import validate_local_path, _check_local_volume
            output = validate_local_path(filename, output=True)
            _check_local_volume(output, "Disposition JSON")
            if output.suffix.lower() != ".json":
                raise ValueError("Choisis un nom se terminant par .json.")
            layout = self.get_layout()
            # Exclusive creation protects an imported layout and rejects links.
            # Saving another version uses a new filename.
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(layout, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            self._message("Disposition JSON enregistrée.")
        except FileExistsError:
            self._message("Ce fichier existe déjà. Choisis un nouveau nom pour conserver l'original.", True)
            messagebox.showerror(tr("Choisir un nouveau nom"), tr("Le fichier existant est conservé. Enregistre cette version sous un nouveau nom."), parent=self.winfo_toplevel())
        except (OSError, ValueError, TypeError) as error:
            self._message("La disposition n'a pas été enregistrée.", True)
            messagebox.showerror(tr("Enregistrement impossible"), tr(str(error)), parent=self.winfo_toplevel())

    def _resize(self, event):
        self.scale = max(0.1, min((event.width - 24) / SCREEN_WIDTH, (event.height - 24) / SCREEN_HEIGHT))
        self.origin = ((event.width - SCREEN_WIDTH * self.scale) / 2,
                       (event.height - SCREEN_HEIGHT * self.scale) / 2)
        self.redraw()

    def _screen(self, event):
        return ((self.canvas.canvasx(event.x) - self.origin[0]) / self.scale,
                (self.canvas.canvasy(event.y) - self.origin[1]) / self.scale)

    def _press(self, event):
        self.canvas.focus_set()
        x, y = self._screen(event)
        for widget in reversed(self._layout["widgets"]):
            left, top, right, bottom = widget_bounds(widget)
            if left <= x < right and top <= y < bottom:
                self._selected = widget["id"]
                self._drag = (x - left, y - top)
                self._proposal = copy.deepcopy(widget)
                self._proposal_error = None
                self._sync_controls()
                self.redraw()
                self._message("Glisse la jauge. Échap annule le déplacement.")
                return
        self._message("Seule la zone centrale quadrillée est modifiable.")

    def _motion(self, event):
        if self._drag is None:
            return
        x, y = self._screen(event)
        col = math.floor((x - self._drag[0] - ZONE_X) * COLS / ZONE_WIDTH + 0.5)
        row = math.floor((y - self._drag[1] - ZONE_Y)/25 + 0.5)
        self._proposal = {**self._selected_widget(), "col": col, "row": row}
        changes={'col':col,'row':row}
        try:
            validate_editor_layout(self._edited(**changes))
            self._proposal_error = None
            self._message("Relâche pour placer la jauge ici.")
        except (ValueError, TypeError) as error:
            self._proposal_error = str(error)
            self._message(f"Position refusée : {error}", True)
        self.redraw()

    def _release(self, event):
        if self._drag is None:
            return
        self._motion(event)
        proposal, error = self._proposal, self._proposal_error
        self._drag = self._proposal = None
        self._proposal_error = None
        if error:
            self.redraw()
            self._message(f"Déplacement annulé : {error}", True)
        else:
            changes={k:proposal[k] for k in ('col','row','zone') if k in proposal}
            self._attempt(self._edited(**changes), "Jauge placée sur la grille.")

    def _cancel_drag(self, _event=None):
        self._drag = self._proposal = None
        self._proposal_error = None
        self.redraw()
        self._message("Déplacement annulé.")
        return "break"

    def _coords(self, *coordinates):
        return [value * self.scale + self.origin[index % 2] for index, value in enumerate(coordinates)]

    def _rect(self, *coordinates, **options):
        return self.canvas.create_rectangle(*self._coords(*coordinates), **options)

    def _text(self, x, y, text, *, size=8, color=UI_TEXT, **options):
        return self.canvas.create_text(*self._coords(x, y), text=tr(text), fill=color,
                                       font=("Segoe UI", max(6, round(size * self.scale)), "bold"), **options)

    def _draw_widget(self, widget, *, invalid=False):
        left, top, right, bottom = widget_bounds(widget)
        color = ERROR if invalid else widget["color"]
        background = self._layout["background"]
        track = track_color(color, background)
        parts = _widget_parts(widget)
        if not self._layout.get("wallpaper"):self._rect(left + 1, top + 1, right - 1, bottom - 1, fill=background, outline="")
        sample=75 if widget['kind']=='battery' else (-35 if widget['channel']%2 else 35)
        for name, text in (("title",'BAT' if widget['channel']==0 else f"CH{widget['channel']}"), ("value", f"{sample}%")):
            x, y, width, height = parts[name]
            alignment = parts["text_align"][name]
            anchor = {"left": "w", "right": "e", "center": "center"}[alignment]
            text_x = left + x + {"left": 0, "right": width, "center": width / 2}[alignment]
            self._text(text_x, top + y + height / 2, text, color=color, anchor=anchor, size=7)
        x, y, width, height = parts["gauge"]
        gauge_left, gauge_top = left + x, top + y
        if widget['kind']=='battery':
            self._rect(gauge_left,gauge_top,gauge_left+width,gauge_top+height,fill=track,outline=color)
            self._rect(gauge_left+1,gauge_top+1,gauge_left+width*.75,gauge_top+height-1,fill=color,outline='')
        elif widget["kind"] == "bar":
            self._rect(gauge_left, gauge_top, gauge_left + width, gauge_top + height, fill=track, outline="")
            middle=gauge_left+width/2
            end=middle+width*sample/240
            self._rect(min(middle,end),gauge_top,max(middle,end),gauge_top+height,fill=color,outline="")
        elif widget['kind']=='semicircle':
            # Keep the four-pixel stroke inside the native gauge rectangle.
            arc = self._coords(gauge_left + 2, gauge_top + 2, gauge_left + width - 2, gauge_top + height - 2)
            self.canvas.create_arc(*arc, start=0, extent=180, style="arc", outline=track, width=max(2, self.scale * 4))
            # Twelve o'clock is 90 degrees in Tk; positive channel values turn clockwise.
            self.canvas.create_arc(*arc,start=90,extent=-90*sample/120,style="arc",outline=color,width=max(2,self.scale*4))
        if widget["id"] == self._selected or invalid:
            self._rect(left + 0.5, top + 0.5, right - 0.5, bottom - 0.5,
                       outline=ERROR if invalid else ACCENT, width=2, dash=(4, 3) if invalid else ())

    def redraw(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        full=self._layout['schema']==12
        photo=self._layout.get('wallpaper')
        self._rect(0,0,SCREEN_WIDTH,SCREEN_HEIGHT,fill=self._layout['background'] if full else '#303943',outline='#71808f')
        if photo:
            from PIL import ImageTk,Image
            from dashboard_wallpaper import photo as decode_photo
            key=(photo,self.scale)
            if getattr(self,'_wallpaper_key',None)!=key:
                size=(max(1,round(240*self.scale)),max(1,round(320*self.scale)))
                self._wallpaper_photo=ImageTk.PhotoImage(decode_photo(photo).resize(size,Image.Resampling.NEAREST),master=self.canvas)
                self._wallpaper_key=key
            self.canvas.create_image(*self._coords(0,0),anchor='nw',image=self._wallpaper_photo,tags='wallpaper')
        else:self._wallpaper_key=self._wallpaper_photo=None
        if self._layout.get('header')=='battery_only':
            from dashboard_header import BODY,TIP,INK,FILL,TRACK
            x,y,w,h=BODY
            self._rect(x,y,x+w,y+h,fill=TRACK,outline=INK,tags='mini_battery')
            self._rect(x+2,y+2,x+2+round((w-4)*0.75),y+h-2,fill=FILL,outline='',tags='mini_battery')
            x,y,w,h=TIP;self._rect(x,y,x+w,y+h,fill=INK,outline='',tags='mini_battery')
        else:
            if not full:self._rect(0, 0, SCREEN_WIDTH, 23, fill="#424d59", outline="")
            self._text(10, 12, "MODÈLE", size=7, color="#aeb8c2", anchor="w")
            self._text(230, 12, "modèle 01", size=7, color="#aeb8c2", anchor="e")
            self._text(12, 42, "BATTERIE", size=7, color="#9ba8b5", anchor="w")
            self._text(12, 63, "7.7 V", size=11, color="#aeb8c2", anchor="w")
            self._rect(130, 32, 228, 58, outline="#687585")
            self._rect(130, 62, 228, 88, outline="#687585")
            self._text(139, 45, "RX       —", color="#9ba8b5", anchor="w")
            self._text(139, 75, "RSSI    —", color="#9ba8b5", anchor="w")
            self._text(120, 130, "A · HAUT D’ORIGINE", size=9, color="#aeb8c2")
            self._text(120, 149, "Aperçu schématique", size=7, color="#9ba8b5")
        self._text(120, 183, "B · GRILLE MODIFIABLE · 6 × 4", size=7, color=ACCENT)
        self._rect(ZONE_X, ZONE_Y, ZONE_X + ZONE_WIDTH, ZONE_Y + ZONE_HEIGHT,
                   fill="" if photo else self._layout["background"], outline=ACCENT, width=1)
        for col in range(1, COLS):
            x = ZONE_X + col * ZONE_WIDTH // COLS
            self.canvas.create_line(*self._coords(x, ZONE_Y, x, ZONE_Y + ZONE_HEIGHT), fill="#527187", dash=(2, 3))
        for row in range(1, ROWS):
            y = ZONE_Y + row * ZONE_HEIGHT // ROWS
            self.canvas.create_line(*self._coords(ZONE_X, y, ZONE_X + ZONE_WIDTH, y), fill="#527187", dash=(2, 3))
        for widget in self._layout["widgets"]:
            if self._drag is not None and widget["id"] == self._selected:
                continue
            self._draw_widget(widget)
        if self._proposal is not None:
            self._draw_widget(self._proposal, invalid=self._proposal_error is not None)
        self._text(120, 311, "Valeurs d’exemple", size=5, color="#aeb8c2")


def main():
    root = tk.Tk()
    root.title(tr("DDF-350 · Éditeur de dashboard"))
    root.geometry("860x790")
    root.minsize(780, 690)
    DashboardEditor(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
