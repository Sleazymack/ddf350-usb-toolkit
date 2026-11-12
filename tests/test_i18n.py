"""Language choice, persistence, translated workflows; no USB or real settings."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import i18n
import wizard
from pc import ddf350_hid as hid


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=mock.patch.dict(os.environ,{'LOCALAPPDATA':self.temp.name})
        self.env.start();self.addCleanup(self.env.stop);self.addCleanup(i18n.set_language,'fr')
    def test_queries_do_not_write_and_choices_survive_reload(self):
        self.assertEqual(i18n.load_language(),'en');self.assertFalse(i18n.preferences_path().exists())
        for language in ('en','fr'):
            i18n.save_language(language);self.assertEqual(i18n.load_language(),language)
        self.assertEqual(list(i18n.preferences_path().parent.glob('*.tmp')),[])
    def test_unknown_or_corrupt_preferences_fall_back_without_overwriting(self):
        path=i18n.preferences_path();path.parent.mkdir(parents=True)
        for content in ('oops','[]','null','{"schema":1,"language":"fr"}','{"schema":2,"language":"xx"}'):
            path.write_text(content);self.assertEqual(i18n.load_language(),'en');self.assertEqual(path.read_text(),content)
        with self.assertRaises(ValueError):i18n.save_language('xx')
    def test_dynamic_messages_are_translated_but_identifiers_remain_unchanged(self):
        i18n.set_language('en')
        self.assertEqual(i18n.tr('Transfert : 2 / 4 blocs vérifiés'),'Transfer: 2 / 4 blocks verified')
        self.assertEqual(i18n.tr('USB actif · CH1 : 123    CH2 : 456 · lecture automatique'),'USB active · CH1: 123    CH2 : 456 · automatic reading')
        self.assertEqual(i18n.tr('ch123456'),'ch123456')


class LanguageWorkflowTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('en');self.addCleanup(i18n.set_language,'fr')
        self.persist=mock.patch.object(i18n,'save_language');self.save=self.persist.start();self.addCleanup(self.persist.stop)
        self.reader=mock.patch.object(hid,'Reader');self.factory=self.reader.start();self.addCleanup(self.reader.stop)
        self.root=tk.Tk();self.root.attributes('-alpha',0)
        self.ui=wizard.Wizard(self.root,auto_reader=True)
    def tearDown(self):
        self.ui.busy=False;self.ui.close()
    def pick(self,language):
        self.ui.language_combo.current(0 if language=='en' else 1)
        self.ui.language_combo.event_generate('<<ComboboxSelected>>');self.root.update()
    def test_opens_english_without_a_prompt_and_starts_reader_once(self):
        self.root.update()
        self.assertEqual(self.ui.language_combo.get(),'English')
        self.assertTrue(self.ui.language_combo.winfo_ismapped())
        self.assertGreater(self.ui.language_combo.winfo_rootx(),self.ui.play_button.winfo_rootx())
        self.save.assert_not_called();self.ui.next();self.assertEqual(self.ui.step,1)
        self.assertEqual(str(self.ui.forward.cget('state')),'disabled')
        self.factory.return_value.start.assert_called_once()
        self.assertEqual(self.ui.radio_button.cget('text'),'Radio')
        self.assertEqual(self.ui.forward.cget('text'),'Continue')
        self.assertEqual(self.ui.title_label.cget('text'),'Customize the transmitter')
    def test_english_editor_controls_keep_native_json_schema_and_values(self):
        self.ui.choose_custom();editor=self.ui.inline_editor
        before=editor.get_layout()
        self.assertIn('Bar',editor.kind_combo.cget('values'))
        self.assertEqual(editor.theme.get(),'Drift blue')
        editor.apply_theme('Night red')
        self.assertEqual(editor.get_layout()['background'],'#241b25')
        themed=editor.get_layout()
        self.ui.play_button.invoke();self.assertTrue(self.ui.pc_mode)
        self.assertEqual(self.ui.title_label.cget('text'),'Activate radio on PC')
        self.ui.radio_button.invoke();self.assertEqual(self.ui.inline_editor.get_layout(),themed)
        self.assertEqual(self.ui.inline_editor.theme.get(),'Night red')
    def test_language_change_preserves_layout_and_is_blocked_during_transfer(self):
        self.ui.choose_custom();self.ui.inline_editor.apply_theme('Night red')
        layout=self.ui.inline_editor.get_layout()
        self.pick('fr')
        self.assertEqual(self.ui.inline_editor.get_layout(),layout)
        self.assertEqual(self.ui.language_combo.get(),'Français');self.save.assert_called_once_with('fr')
        self.assertEqual(self.ui.back.cget('text'),'Retour');self.assertEqual(self.ui.step,3)
        self.ui.busy=True;self.pick('en')
        self.assertEqual(i18n.language(),'fr');self.assertEqual(self.ui.language_combo.get(),'Français')
        self.ui.busy=False;self.ui.show_pc_mode(start_reader=False);self.pick('en')
        self.assertTrue(self.ui.pc_mode);self.assertEqual(self.ui.back.cget('text'),'Back')
        self.factory.return_value.start.assert_called_once()
    def test_worker_log_is_translated_for_display_without_rewriting_source_record(self):
        self.ui.step=6;self.ui.render()
        self.ui.log('Sauvegarde enregistrée et vérifiée sur le PC.')
        self.assertIn('Backup saved and verified on PC.',self.ui.log_view.get('1.0','end'))
        self.assertIn('Sauvegarde enregistrée',self.ui.log_lines[-1][0])
