"""Page navigation and explicit installation boundary; all USB calls mocked."""
import importlib.util
import sys
from pathlib import Path
import unittest
import tempfile
import json
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
HAVE_TK=importlib.util.find_spec('tkinter') is not None
if HAVE_TK:
    import tkinter as tk
    import wizard


@unittest.skipUnless(HAVE_TK,'Tk unavailable')
class WizardTests(unittest.TestCase):
    def setUp(self):
        import app
        self.source_guard=mock.patch.object(app,'find_official_firmware',return_value=None)
        self.source_guard.start();self.addCleanup(self.source_guard.stop)
        self.guard=mock.patch.object(wizard.installer,'powershell',side_effect=AssertionError('Unexpected hardware enumeration'))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.root=tk.Tk();self.root.withdraw();self.ui=wizard.Wizard(self.root)
    def tearDown(self):
        self.ui.busy=False;self.ui.close()
    def test_no_radio_access_on_start_and_each_page_is_separate(self):
        self.assertEqual(self.ui.step,1)
        self.assertEqual(str(self.ui.forward.cget('state')),'disabled')
        self.ui.confirm_version();self.assertEqual(self.ui.step,1)
        self.ui.source.set('verified-local.bin');self.ui.next();self.assertEqual(self.ui.step,2)
        self.ui.select_dashboard('ch123456');self.ui.next()
        self.assertEqual(self.ui.step,3)
        self.assertIsNone(self.ui.inline_editor)
        self.assertIsNone(self.ui.worker_handle)
    def test_custom_editor_is_a_page_and_preserves_changes(self):
        self.ui.confirm_version();self.ui.choose_custom()
        self.assertEqual(self.ui.step,3)
        self.assertIsNotNone(self.ui.inline_editor)
        layout=self.ui.inline_editor.get_layout()
        self.ui.previous();self.assertEqual(self.ui.step,2)
        self.ui.choose_custom()
        self.assertEqual(self.ui.inline_editor.get_layout(),layout)
    def test_connection_page_requires_explicit_detection(self):
        self.ui.step=5;self.ui.render()
        self.assertEqual(str(self.ui.forward.cget('state')),'disabled')
        self.ui.next();self.assertEqual(self.ui.step,5)
    def test_confirm_install_is_required_and_close_is_blocked_during_transfer(self):
        self.ui.step=6;self.ui.render()
        with mock.patch.object(self.ui,'install') as install:
            self.assertEqual(install.call_count,0)
            self.ui.next();install.assert_called_once()
        self.ui.busy=True
        with mock.patch.object(wizard.messagebox,'showinfo'):
            self.ui.close()
        self.assertFalse(self.ui.closed)
    def test_failed_install_is_reported_without_advancing(self):
        self.ui.step=6;self.ui.render();self.ui.busy=True
        self.ui.events.put(('install_error','Windows annulé',None))
        self.ui.poll()
        self.assertFalse(self.ui.busy);self.assertEqual(self.ui.step,6)
        self.assertEqual(self.ui.status.get(),'Windows annulé')

    def test_worker_journal_handles_partial_lines_without_duplicates(self):
        self.ui.step=6;self.ui.render()
        with tempfile.TemporaryDirectory() as folder:
            self.ui.job_directory=Path(folder)
            path=Path(folder)/'journal.jsonl'
            record=json.dumps({'time':'2026-11-03T23:40:00+01:00','phase':'checking','message':'Sauvegarde vérifiée'},ensure_ascii=False).encode('utf-8')
            path.write_bytes(record[:25]);self.ui.read_worker_log()
            self.assertEqual(self.ui.log_lines,[])
            with path.open('ab') as f:f.write(record[25:]+b'\n')
            self.ui.read_worker_log();self.ui.read_worker_log()
            self.assertEqual(len(self.ui.log_lines),1)
            self.assertIn('Sauvegarde vérifiée',self.ui.log_view.get('1.0','end'))
            self.assertEqual(str(self.ui.log_view.cget('state')),'disabled')

    def test_error_is_visible_in_embedded_log(self):
        self.ui.step=6;self.ui.render()
        self.ui.finish_error('Erreur Windows 1223')
        self.assertIn('Erreur Windows 1223',self.ui.log_view.get('1.0','end'))
        self.assertTrue(self.ui.log_lines[-1][1])


if __name__=='__main__':unittest.main()
