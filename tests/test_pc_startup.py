"""Opt-in Windows startup tests. Registry is always an in-memory fake."""
from contextlib import nullcontext
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pc_startup as startup


class FakeRegistry:
    HKEY_CURRENT_USER='current-user'
    KEY_READ=1;KEY_SET_VALUE=2;REG_SZ=1
    def __init__(self):self.values={'unrelated':('preserve',1)};self.writes=[]
    def OpenKey(self,hive,key,*args):
        if hive!=self.HKEY_CURRENT_USER or key!=startup.RUN_KEY:raise AssertionError('Wrong registry scope')
        return nullcontext(self)
    CreateKeyEx=OpenKey
    def QueryValueEx(self,key,name):
        if name not in self.values:raise FileNotFoundError(name)
        return self.values[name]
    def SetValueEx(self,key,name,unused,kind,value):self.values[name]=(value,kind);self.writes.append(name)
    def DeleteValue(self,key,name):del self.values[name];self.writes.append(name)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='DDF PC startup ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.reg=FakeRegistry()
        self.env=mock.patch.dict(os.environ,{'LOCALAPPDATA':str(self.root)})
        self.env.start();self.addCleanup(self.env.stop)
        self.api=mock.patch.object(startup,'registry',return_value=self.reg)
        self.api.start();self.addCleanup(self.api.stop)
    def test_no_registration_on_query_and_source_run_is_refused(self):
        self.assertFalse(startup.is_enabled());self.assertEqual(self.reg.writes,[])
        with mock.patch.object(sys,'frozen',False,create=True):
            with self.assertRaises(OSError):startup.enable()
        self.assertEqual(self.reg.writes,[])
    def test_enable_makes_verified_stable_copy_and_disable_only_removes_own_value(self):
        source=self.root/'application.exe';data=b'MZ'+bytes(range(256))*5;source.write_bytes(data)
        with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'executable',str(source)),mock.patch.object(startup.p,'_check_local_volume'):
            startup.enable()
        self.assertTrue(startup.is_enabled())
        command=self.reg.values[startup.VALUE_NAME][0]
        self.assertIn('--pc-mode --minimized',command)
        self.assertNotIn('--install-job',command)
        copies=list(startup.startup_folder().glob('*.exe'))
        self.assertEqual(len(copies),1);self.assertEqual(copies[0].read_bytes(),data)
        startup.disable();self.assertFalse(startup.is_enabled())
        self.assertEqual(self.reg.values['unrelated'],('preserve',1))
        self.assertEqual(copies[0].read_bytes(),data)
    def test_foreign_value_cannot_be_overwritten_or_removed(self):
        self.reg.values[startup.VALUE_NAME]=('another-application.exe',1)
        with mock.patch.object(startup,'stage_executable') as stage:
            with self.assertRaises(OSError):startup.enable()
            stage.assert_not_called()
        with self.assertRaises(OSError):startup.disable()
        self.assertEqual(self.reg.writes,[])
    def test_corrupt_existing_stable_copy_prevents_registration(self):
        source=self.root/'application.exe';source.write_bytes(b'MZverified')
        with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'executable',str(source)),mock.patch.object(startup.p,'_check_local_volume'):
            destination=startup.stage_executable();destination.write_bytes(b'MZchanged')
            with self.assertRaises(OSError):startup.enable()
        self.assertEqual(self.reg.writes,[])
    def test_overlong_command_is_refused_before_registry_write(self):
        with mock.patch.object(startup,'stage_executable',return_value=Path('C:/'+('x'*270)+'.exe')):
            with self.assertRaises(OSError):startup.enable()
        self.assertEqual(self.reg.writes,[])

    def test_installed_application_uses_its_installed_location_without_extra_copy(self):
        source=startup.installed_executable();source.parent.mkdir(parents=True);source.write_bytes(b'MZinstalled')
        with mock.patch.object(sys,'frozen',True,create=True),mock.patch.object(sys,'executable',str(source)),mock.patch.object(startup.p,'_check_local_volume'):
            startup.enable()
        self.assertTrue(startup.is_enabled())
        self.assertIn(str(source),self.reg.values[startup.VALUE_NAME][0])
        self.assertFalse(startup.startup_folder().exists())

    @unittest.skipUnless(sys.platform=='win32','Windows distribution entry point')
    def test_uninstaller_cleanup_does_not_open_gui_or_reader(self):
        import app
        with mock.patch.object(startup,'disable') as disable,mock.patch.object(app.tk,'Tk',side_effect=AssertionError('Unexpected GUI')):
            app.main(['--remove-installed-startup'])
        disable.assert_called_once()


if __name__=='__main__':unittest.main()
