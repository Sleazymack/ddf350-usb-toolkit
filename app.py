"""French desktop entry point for the standalone DDF-350 USB toolkit.

The wizard installs only after an explicit user action, via a separate elevated
worker. The file preparation engine remains independently usable offline.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
import i18n
from i18n import tr

import patch_firmware as patcher


EDITIONS = (
    ("original", "Original", "L'accueil constructeur", (1, 2, 5, 6)),
    ("ch1234", "CH1 · CH2 · CH3 · CH4", "Le thème d'origine, quatre voies", (1, 2, 3, 4)),
    ("ch123456", "CH1 à CH6", "Les six voies sur un seul écran", (1, 2, 3, 4, 5, 6)),
    ("strip_drift", "Strip Drift", "Barres segmentées · vert et cyan", (1,2,3,4)),
    ("led_segments", "LED Segments", "Deux cadrans segmentés · vert et cyan", (1,2,3,4)),
    ("purple_drift", "Purple Drift", "Deux aiguilles · violet et vert", (1,2,3,4)),
)
BG, PANEL, INK, MUTED, ACCENT = "#101924", "#1b2939", "#eff5fc", "#a6b5c8", "#55dfd0"
OFFICIAL_DOWNLOAD_URL = "https://www.dumborc.com/?page_id=930"


def bundled_firmware_path():
    """Locate the release resource in its package or in the source checkout."""
    root = getattr(sys, '_MEIPASS', None) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    if root is None:
        return None
    path=Path(root)/'firmware'/'DDF-2.0.5.bin'
    return path if path.is_file() else None


def find_official_firmware():
    """Select and verify the base before offering dashboard creation."""
    candidate = None if getattr(sys,'frozen',False) else os.environ.get("DDF350_OFFICIAL_FIRMWARE")
    candidate = candidate or bundled_firmware_path()
    if not candidate:
        return None
    content = patcher.read_regular_file(candidate)
    patcher._require_original(content)
    return str(candidate)


def prepare_file(source: str, destination: str, dashboard: str, usb_1ms: bool, layout=None) -> dict:
    """Use the same guarded, hash-pinned engine as the command-line tool."""
    original = patcher.read_regular_file(source)
    options = {"dashboard": dashboard, "usb_1ms": usb_1ms}
    if layout is not None:
        options["layout"] = patcher.dashboard_custom.current_layout(layout)
    result = patcher.build_patch(original, **options)
    report = patcher.make_manifest(original, result, "patch")
    patcher.write_new_output(destination, result, source=source)
    report["file_written"] = True
    return report


class Application:
    def __init__(self, root: tk.Tk, *, onboarding=False):
        self.root = root
        self.root.title(tr("DDF-350 · USB Toolkit"))
        self.root.geometry("1020x800")
        self.root.minsize(940, 780)
        self.root.configure(bg=BG)
        self.source = tk.StringVar()
        self.source_display = tk.StringVar()
        self.official_resource = None
        self.dashboard = tk.StringVar(value="original")
        self.fast = tk.BooleanVar(value=True)
        self.status = i18n.StringVar(value="Choisis une présentation, puis le firmware officiel V2.0.5.")
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.closed = False
        self.viewer = None
        self.custom_layout = None
        self.editor_window = None
        self.version_confirmed = not onboarding
        self.cards = []
        self.controls = []
        self.poll_id = None
        try:
            self.official_resource = find_official_firmware()
        except (OSError, ValueError) as error:
            self.status.set("Le fichier fourni n'a pas été reconnu : " + str(error))
        self.source.trace_add("write", lambda *_: self.source_display.set(
            "Firmware officiel 2.0.5 sélectionné · fichier vérifié" if self.official_resource and self.source.get() == self.official_resource
            else self.source.get()))
        if self.official_resource:
            self.source.set(self.official_resource)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(80, self.poll)
        if onboarding:
            self.root.after_idle(self.show_compatibility)

    def label(self, parent, text, *, size=11, color=INK, bold=False, **kwargs):
        return tk.Label(parent, text=tr(text), bg=parent.cget("bg"), fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kwargs)

    def _build(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=28, pady=22)
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        self.label(header, "DDF-350", size=25, bold=True).pack(side="left")
        self.label(header, "USB TOOLKIT", size=11, color=ACCENT, bold=True).pack(side="left", padx=15)
        self.label(header, patcher.VERSION, size=9, color=MUTED).pack(side="right")
        self.label(outer, "Choisis un préréglage ou compose ton propre dashboard.", size=13, color=MUTED).pack(anchor="w", pady=(3, 6))
        self.label(outer, "COMPATIBILITÉ : DDF-350 · firmware officiel 2.0.5 uniquement", size=10, color=ACCENT, bold=True).pack(anchor="w", pady=(0, 12))
        self.label(outer, "1. Choisir le dashboard", size=12, bold=True).pack(anchor="w", pady=(0, 9))
        row = tk.Frame(outer, bg=BG)
        row.pack(fill="x")
        for i, (key, title, detail, channels) in enumerate(EDITIONS):
            row.columnconfigure(i, weight=1, uniform="edition")
            card = tk.Frame(row, bg=PANEL, highlightthickness=2)
            card.grid(row=0, column=i, padx=(0 if i == 0 else 7, 0 if i == 2 else 7), sticky="nsew")
            radio = tk.Radiobutton(card, text=tr(title), variable=self.dashboard, value=key,
                                   command=self.refresh_cards, bg=PANEL, fg=INK, selectcolor=PANEL,
                                   activebackground=PANEL, activeforeground=ACCENT,
                                   font=("Segoe UI", 11, "bold"), anchor="w")
            radio.pack(fill="x", padx=10, pady=(11, 2))
            self.controls.append(radio)
            self.label(card, detail, size=9, color=MUTED).pack(anchor="w", padx=13)
            canvas = tk.Canvas(card, width=235, height=142, bg=PANEL, highlightthickness=0)
            canvas.pack(fill="x", padx=13, pady=(8, 1))
            canvas.bind("<Configure>", lambda event, c=canvas, ch=channels: self.paint_channels(c, ch))
            canvas.bind("<Button-1>", lambda _event, choice=key: self.select_dashboard(choice))
            self.label(card, "Schéma des voies affichées", size=8, color=MUTED).pack(anchor="w", padx=13, pady=(0, 10))
            self.cards.append((key, card))
        self.refresh_cards()
        custom_row = tk.Frame(outer, bg=BG)
        custom_row.pack(fill="x", pady=(10, 12))
        editor_button = ttk.Button(custom_row, text=tr("Composer mon dashboard…"), command=self.open_editor)
        editor_button.pack(side="left", ipady=4)
        self.controls.append(editor_button)
        self.label(custom_row, "Glisser les jauges · régler les couleurs · menus conservés", size=10, color=MUTED).pack(side="left", padx=12)
        self.label(outer, "2. Choisir le fichier officiel", size=12, bold=True).pack(anchor="w", pady=(0, 7))
        source_row = tk.Frame(outer, bg=BG)
        source_row.pack(fill="x")
        entry = ttk.Entry(source_row, textvariable=self.source_display, state="readonly", font=("Segoe UI", 10))
        self.source_entry = entry
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        browse = ttk.Button(source_row, text=tr("Parcourir…"), command=self.browse)
        browse.pack(side="right", padx=(10, 0), ipady=4)
        self.controls.extend([entry, browse])
        self.label(outer, "DDF-350 V2.0.5 d'origine · le fichier est vérifié avant toute préparation.", size=9, color=MUTED).pack(anchor="w", pady=(5, 12))
        fast = tk.Checkbutton(outer, text=tr("USB rapide · intervalle de 1 ms"), variable=self.fast,
                              bg=BG, fg=INK, activebackground=BG, activeforeground=INK,
                              selectcolor=PANEL, font=("Segoe UI", 11), anchor="w")
        fast.pack(anchor="w")
        self.controls.append(fast)
        self.label(outer, "Décoché : intervalle natif de 20 ms. Ce réglage ne représente pas la latence totale du jeu.", size=9, color=MUTED).pack(anchor="w", pady=(2, 13))
        actions = tk.Frame(outer, bg=BG)
        actions.pack(fill="x")
        self.create_button = tk.Button(actions, text=tr("Créer le fichier…"), command=self.create,
                                       bg=ACCENT, fg=BG, activebackground="#86ebdf", activeforeground=BG,
                                       font=("Segoe UI", 12, "bold"), relief="flat", padx=22, pady=10)
        self.create_button.pack(side="left")
        self.controls.append(self.create_button)
        self.reader_button = ttk.Button(actions, text=tr("Lire CH1 / CH2 en direct"), command=self.open_reader)
        self.reader_button.pack(side="left", padx=15, ipady=7)
        status = tk.Label(outer, textvariable=self.status, bg=BG, fg=INK,
                          font=("Segoe UI", 10), anchor="w", justify="left", wraplength=920)
        status.pack(fill="x", pady=(14, 8))
        self.label(outer, "Version expérimentale · fichiers préparés sur le PC, installation sur la radio séparée.", size=9, color=MUTED).pack(anchor="w", side="bottom")

    def paint_channels(self, canvas, channels):
        import tkinter.font as font
        canvas.delete("all")
        text_font=font.Font(root=self.root,family='Segoe UI',size=9,weight='bold')
        height=6*(text_font.metrics('linespace')+6)+12
        if int(float(str(canvas.cget('height'))))!=height:canvas.configure(height=height)
        width=max(2,canvas.winfo_width()-4)
        step=(height-12)/len(channels)
        left=text_font.measure('CH6')+12
        right=max(left+1,width-text_font.measure('0%')-12)
        for i, channel in enumerate(channels):
            y=6+(i+.5)*step
            canvas.create_text(2,y,text=tr(f'CH{channel}'),fill='#d9eaff',anchor='w',font=('Segoe UI',9,'bold'))
            canvas.create_rectangle(left,y-4,right,y+4,fill='#324b65',outline='')
            canvas.create_line((left+right)/2,y-4,(left+right)/2,y+4,fill='#63b7f7')
            canvas.create_text(width, y, text=tr("0%"), fill=MUTED, anchor="e", font=("Segoe UI", 9))

    def select_dashboard(self, key):
        if not self.busy:
            self.dashboard.set(key)
            self.refresh_cards()

    def refresh_cards(self):
        for key, card in self.cards:
            card.configure(highlightbackground=ACCENT if self.dashboard.get() == key else "#304154")

    def browse(self):
        self.choose_update(self.root)

    def create(self):
        if self.busy:
            return
        if not self.version_confirmed:
            self.show_compatibility()
            return
        source = self.source.get().strip()
        if not source:
            messagebox.showinfo(tr("Fichier officiel"), tr("Choisis d'abord le firmware officiel V2.0.5."), parent=self.root)
            return
        choice, fast = self.dashboard.get(), self.fast.get()
        layout = copy.deepcopy(self.custom_layout) if choice == "custom" else None
        if choice == "custom" and layout is None:
            self.open_editor()
            return
        default = f"DDF-{'USB1ms' if fast else 'USB20ms'}-{choice}.bin"
        destination = filedialog.asksaveasfilename(parent=self.root, title=tr("Créer un nouveau fichier sur le PC"),
                                                   initialfile=default, defaultextension=".bin",
                                                   filetypes=[(tr("Firmware DDF"), "*.bin")], confirmoverwrite=False)
        if not destination:
            return
        self.busy = True
        for control in self.controls:
            control.configure(state="disabled")
        self.status.set("Vérification du fichier et préparation en cours…")

        def work():
            try:
                report = prepare_file(source, destination, choice, fast, layout) if layout is not None else prepare_file(source, destination, choice, fast)
                self.events.put(("done", destination, report))
            except Exception as error:
                self.events.put(("error", str(error), None))
        threading.Thread(target=work, daemon=True, name="Preparation DDF-350").start()

    def poll(self):
        if self.closed:
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        try:
            kind, value, report = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for control in self.controls:
                control.configure(state="normal")
            self.source_entry.configure(state="readonly")
            if kind == "done":
                self.status.set(f"Fichier créé et vérifié : {value}\nAucune installation n'a été effectuée sur la radio.")
            else:
                self.status.set("La préparation n'a pas abouti. Consulte le message pour corriger le problème.")
                messagebox.showerror(tr("Préparation impossible"), tr(value), parent=self.root)
        self.poll_id = self.root.after(80, self.poll)

    def open_reader(self):
        if self.viewer is not None and not self.viewer.closed:
            self.viewer.root.lift()
            return
        try:
            from pc.ddf350_hid import Viewer
            self.viewer = Viewer(parent=self.root)
            self.viewer.run()
        except Exception as error:
            messagebox.showerror(tr("Lecture PC indisponible"), tr(str(error)), parent=self.root)

    def open_editor(self):
        if self.busy:
            return
        if self.editor_window is not None and self.editor_window.winfo_exists():
            self.editor_window.lift()
            return
        from editor import DashboardEditor
        window = tk.Toplevel(self.root)
        self.editor_window = window
        window.title(tr("DDF-350 · Éditeur de dashboard"))
        window.geometry("1180x800")
        window.minsize(1050, 740)
        window.configure(bg=BG)
        window.transient(self.root)
        editor = DashboardEditor(window)
        editor.pack(fill="both", expand=True)
        if self.custom_layout is not None:
            editor.set_layout(self.custom_layout)
        actions = tk.Frame(window, bg=BG)
        actions.pack(fill="x", padx=24, pady=12)

        def apply():
            try:
                selected = editor.get_layout()
            except (ValueError, TypeError) as error:
                messagebox.showerror(tr("Disposition à corriger"), tr(str(error)), parent=window)
                return
            self.custom_layout = selected
            self.dashboard.set("custom")
            self.refresh_cards()
            self.status.set(f"Dashboard personnalisé sélectionné · {len(selected['widgets'])} jauges. Choisis le fichier officiel puis crée le résultat.")
            window.destroy()
        ttk.Button(actions, text=tr("Utiliser ce dashboard"), command=apply).pack(side="right", ipady=6)
        ttk.Button(actions, text=tr("Annuler"), command=window.destroy).pack(side="right", padx=12, ipady=6)
        window.grab_set()

    def show_compatibility(self):
        if self.closed:
            return
        window = tk.Toplevel(self.root)
        window.title(tr("DDF-350 · Vérifier la version"))
        window.configure(bg=BG)
        window.geometry("730x460")
        window.resizable(False, False)
        window.transient(self.root)
        panel = tk.Frame(window, bg=BG)
        panel.pack(fill="both", expand=True, padx=28, pady=24)
        self.label(panel, "Avant de personnaliser ta radio", size=20, bold=True).pack(anchor="w")
        self.label(panel, "Seul le firmware officiel DDF-350 2.0.5 est compatible.", size=12, color=ACCENT, bold=True).pack(anchor="w", pady=(12, 8))
        self.label(panel, "Lis la version dans les informations de la radio.\nL'application ne la détecte pas automatiquement par USB.", size=11, color=MUTED, justify="left").pack(anchor="w", pady=(0, 18))

        def confirmed():
            self.version_confirmed = True
            self.status.set("Version 2.0.5 déclarée. Le fichier officiel sera vérifié avant la génération.")
            window.destroy()

        ttk.Button(panel, text=tr("Ma radio est déjà en 2.0.5 · continuer"), command=confirmed).pack(fill="x", ipady=9, pady=(0, 12))
        self.label(panel, "Le fichier source est contrôlé par son empreinte exacte.\nLe numéro de version affiché seul ne suffit pas à valider un fichier.", size=9, color=MUTED, justify="left").pack(anchor="w", pady=(18, 0))
        window.grab_set()

    def open_official_download(self):
        webbrowser.open(OFFICIAL_DOWNLOAD_URL)

    def choose_update(self, parent):
        path = filedialog.askopenfilename(parent=parent, title=tr("Firmware officiel 2.0.5"),
                                           filetypes=[(tr("Firmware DDF"), "*.bin")])
        if not path:
            return
        try:
            original = patcher.read_regular_file(path)
            patcher._require_original(original)
        except (OSError, ValueError) as error:
            messagebox.showerror(tr("Fichier incompatible"), tr(str(error)), parent=parent)
            return
        self.official_resource = path
        self.source.set(path)
        messagebox.showinfo(tr("Fichier prêt"), tr("Le fichier officiel 2.0.5 est vérifié et sélectionné. L'installation sur la radio reste séparée."), parent=parent)

    def close(self):
        if self.busy:
            messagebox.showinfo(tr("Préparation en cours"), tr("Attends la fin de la création du fichier avant de fermer."), parent=self.root)
            return
        self.closed = True
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        if self.viewer is not None and not self.viewer.closed:
            self.viewer.close()
        self.root.destroy()


def self_test(destination: str):
    """Check the packaged UI without selecting firmware or opening USB."""
    from pc.ddf350_hid import Viewer
    from editor import DashboardEditor
    root = tk.Tk()
    root.withdraw()
    app = Application(root)
    try:
        root.update_idletasks()
        for key, _title, _detail, _channels in EDITIONS:
            app.select_dashboard(key)
            if app.dashboard.get() != key:
                raise RuntimeError("Dashboard selection did not update")
        report = {"tool_version": patcher.VERSION, "result": "PASS",
                  "language": i18n.language(),
                  "choices": [edition[0] for edition in EDITIONS],
                  "tk_available": True, "reader_importable": callable(Viewer),
                  "editor_importable": callable(DashboardEditor),
                  "official_firmware_available_and_verified": bool(app.official_resource),
                  "firmware_bundled": bundled_firmware_path() is not None,
                  "official_download_url": OFFICIAL_DOWNLOAD_URL,
                  "radio_opened": False, "firmware_written": False}
        from wizard import Wizard
        wizard_root = tk.Tk()
        wizard_root.withdraw()
        wizard = Wizard(wizard_root)
        try:
            wizard.confirm_version()
            import startup_media
            report['startup_media_import_and_conversion_verified']=startup_media.self_test()
            report['startup_animation_available']=True
            report['startup_media_bundled']=False
            report['startup_gif_limits']={'bytes_exclusive':startup_media.GIF_BYTES,'max_fps':5}
            report['startup_default_original']=wizard.startup_media is None
            report['distribution']='portable-only'
            from dashboard_fullscreen import THEMES,scene as theme_scene
            report['drift_theme_presets']={key:len(theme_scene(key))+1 for key in THEMES}
            if wizard.source.get():
                import startup_animation
                original=patcher.read_regular_file(wizard.source.get())
                target=patcher.build_patch(original,usb_1ms=True)
                report['native_startup_preserved']=all(target[site:site+len(signature)]==signature
                    for site,signature in startup_animation.ORIGINAL_SITES.items())
                report['drift_theme_firmware_verified']=all(
                    patcher.inspect_image(patcher.build_patch(original,dashboard=key))['recognized']
                    and patcher.revert_patch(patcher.build_patch(original,dashboard=key))==original
                    for key in THEMES)
            wizard.choose_custom()
            wizard_root.update_idletasks()
            if wizard.step != 3 or wizard.inline_editor is None:
                raise RuntimeError("Wizard editor page unavailable")
            report['wizard_available'] = True
            report['lower_editor_available']=wizard.inline_editor.get_layout()['schema']==6
            report['two_zone_editor_available']=False
            from PIL import Image
            import io,dashboard_wallpaper
            sample=io.BytesIO();Image.new('RGB',(16,16),'teal').save(sample,format='PNG')
            design=wizard.inline_editor.full_background(dashboard_wallpaper.convert(sample.getvalue()))
            wizard.inline_editor.set_layout(design)
            report['full_home_wallpaper_available']=bool(wizard.inline_editor.canvas.find_withtag('wallpaper'))
            wizard.inline_editor.header_check.invoke()
            design=wizard.inline_editor.get_layout()
            report['minimal_battery_header_available']=(design.get('header')=='battery_only'
                and len(wizard.inline_editor.canvas.find_withtag('mini_battery'))==3)
            if not report['minimal_battery_header_available']:
                raise RuntimeError("Minimal battery header unavailable in the custom editor")
            wizard.step=4;wizard.render()
            report['startup_options_collapsed']=wizard.preview_canvas is None and not hasattr(wizard.media_panel,'apply')
            if wizard.source.get():
                media=startup_media.from_bytes(sample.getvalue(),name='test.png')
                target=patcher.build_patch(original,dashboard='custom',layout=design,startup_photo=media.asset)
                report['wallpaper_and_boot_media_verified']=(patcher.inspect_image(target).get('startup_photo') is True and patcher.revert_patch(target)==original)
                if not report['wallpaper_and_boot_media_verified']:raise RuntimeError('Photo workflow failed.')
            report['installer_importable'] = True
            wizard.step = 6
            wizard.render()
            wizard.log('Journal intégré prêt.')
            report['installation_journal_available'] = bool(wizard.log_view)
            report['compact_fixed_window'] = not any(map(int, wizard.root.resizable()))
            report['automatic_reader_available'] = callable(wizard.start_game_reader)
            wizard.show_pc_mode(start_reader=False)
            report['pc_activation_page_available'] = len(wizard.pc_panels) == 2
            wizard.show_radio_mode()
            report['unified_radio_and_pc_navigation'] = not wizard.pc_mode and wizard.radio_button.winfo_exists() == 1
            from sync_tray import TrayIcon, SingleInstance
            report['tray_backend_available'] = callable(TrayIcon) and callable(SingleInstance)
            report['language_dropdown_available']=wizard.language_combo.get()==('English' if i18n.language()=='en' else 'Français')
            wizard.step=2;wizard.render()
            keys=[]
            for _ in wizard.gallery_entries:
                keys.append(wizard.dashboard.get());wizard.move_gallery(1)
            report['gallery_all_choices_verified']=set(keys)=={e[0] for e in EDITIONS}|{'custom'}
        finally:
            wizard.close()
        target = patcher.validate_local_path(destination, output=True)
        patcher._check_local_volume(target, "Self-test report")
        with target.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
    finally:
        app.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="DDF-350 USB Toolkit")
    parser.add_argument("--self-test", metavar="NEW_REPORT.json", help="Check packaged UI without USB access")
    parser.add_argument('--audit-ui',metavar='NEW_REPORT.json',help='Offline UI geometry and text-size audit; no USB')
    parser.add_argument('--preview-ui',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument("--language", choices=('fr','en'), help="Language for an offline self-test or background launch")
    parser.add_argument("--install-job", metavar="DIRECTORY", help=argparse.SUPPRESS)
    parser.add_argument("--pc-mode", action="store_true", help="Open the live CH1/CH2 PC page")
    parser.add_argument("--minimized", action="store_true", help="Start minimized with the reader active")
    parser.add_argument("--remove-installed-startup", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.preview_ui:
        from wizard import Wizard
        from unittest import mock
        with mock.patch.object(i18n,'save_language'),mock.patch('pc_startup.enable'),mock.patch('pc_startup.disable'):
            i18n.set_language(args.language or i18n.load_language())
            root=tk.Tk();ui=Wizard(root)
            def disabled():ui.status.set('Prévisualisation UI · aucun accès à la radio.')
            ui.start_game_reader=disabled;ui.detect=disabled;ui.install=disabled
            root.mainloop()
        return
    if args.audit_ui:
        from ui_audit import save
        report=save(args.audit_ui)
        if report['result']!='PASS':raise SystemExit(2)
        return
    if args.remove_installed_startup:
        import pc_startup
        pc_startup.disable()
        return
    if args.install_job:
        from installer import run_job
        try:
            run_job(args.install_job)
        except Exception as error:
            from installer import status
            try: status(Path(args.install_job), 'error', str(error))
            except Exception: pass
        return
    if args.self_test:
        i18n.set_language(args.language or i18n.DEFAULT_LANGUAGE)
        self_test(args.self_test)
        return
    from sync_tray import SingleInstance
    instance=SingleInstance()
    try:
        if not instance.acquire():
            instance.show_existing(radio=not (args.pc_mode or args.minimized))
            return
        root = tk.Tk()
        if args.minimized:root.withdraw()
        from wizard import Wizard
        i18n.set_language(args.language or i18n.load_language())
        application=Wizard(root, auto_reader=True, enable_tray=True)
        if args.pc_mode:application.show_pc_mode()
        if args.minimized:root.after_idle(application.hide_to_tray)
        root.mainloop()
    finally:
        instance.close()


if __name__ == "__main__":
    main()
