"""Private bundled-image UX; real local image, no USB or radio transfer."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import i18n
import patch_firmware as p
import wizard


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official input not supplied')
class BundledWorkflowTests(unittest.TestCase):
    def test_legacy_asset_is_ignored_and_preparation_preserves_native_startup(self):
        from test_startup_animation import asset
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);(base/'firmware').mkdir();(base/'assets').mkdir()
            (base/'firmware/DDF-2.0.5.bin').write_bytes(original);(base/'assets/startup.ddfa').write_bytes(asset())
            for language in ('fr','en'):
                i18n.set_language(language)
                with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'_MEIPASS',folder,create=True), \
                     mock.patch.object(app.filedialog,'askopenfilename',side_effect=AssertionError('Unexpected file dialog')):
                    root=tk.Tk();root.attributes('-alpha',0);ui=wizard.Wizard(root)
                    try:
                        ui.confirm_version();root.update();self.assertFalse(hasattr(ui,'startup_checkbox'))
                        ui.choose_custom();ui.next();ui.next()
                        info=p.inspect_image(ui.target);self.assertTrue(info['recognized'])
                        self.assertNotIn('startup_animation',info)
                        import startup_animation
                        for site,signature in startup_animation.ORIGINAL_SITES.items():
                            self.assertEqual(ui.target[site:site+len(signature)],signature)
                        self.assertEqual(info['layout']['schema'],10)
                        self.assertEqual(p.revert_patch(ui.target),original)
                        from test_installer import raw_fixture
                        from test_installer_switching import windows_prefix
                        import installer
                        for version in (1,2):
                            old=p.build_patch(original,dashboard='custom',layout=info['layout'],
                                startup_animation=asset(),startup_player_version=version)
                            before=windows_prefix(raw_fixture(old))
                            after,_,_=installer.plan_transfer(before,ui.target,original)
                            self.assertEqual(after[installer.APP:installer.APP+len(ui.target)],ui.target)
                            self.assertEqual(installer.recognize_installed(after,original),info['variant'])
                    finally:ui.close()
            i18n.set_language('fr')

    def test_french_and_english_editor_and_preparation_never_ask_for_ddf(self):
        original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes();p._require_original(original)
        self.addCleanup(i18n.set_language,'fr')
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'firmware'/'DDF-2.0.5.bin';source.parent.mkdir();source.write_bytes(original)
            for language in ('fr','en'):
                with self.subTest(language=language), \
                     mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'_MEIPASS',folder,create=True), \
                     mock.patch.object(app.filedialog,'askopenfilename',side_effect=AssertionError('Unexpected file dialog')):
                    i18n.set_language(language)
                    root=tk.Tk();root.attributes('-alpha',0);ui=wizard.Wizard(root)
                    try:
                        self.assertEqual(Path(ui.source.get()),source)
                        ui.confirm_version();self.assertEqual(ui.step,2)
                        ui.choose_custom();self.assertIsNotNone(ui.inline_editor)
                        ui.next();self.assertEqual(ui.step,4)
                        ui.next();self.assertEqual(ui.step,5)
                        self.assertTrue(p.inspect_image(ui.target)['recognized'])
                        ui.previous();ui.previous();ui.previous();ui.previous()
                        ui.confirm_version();self.assertEqual(ui.step,2)
                    finally:ui.close()
