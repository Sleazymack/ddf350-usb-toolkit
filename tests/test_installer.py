"""Maintenance transport tests on byte arrays only. Never enumerate USB."""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import installer as i
import patch_firmware as p


def raw_fixture(image):
    raw=bytearray(b'\xff'*i.RAW_SIZE)
    raw[510:512]=b'\x55\xaa'
    for offset,value in ((11,4096),(14,1),(17,512),(19,247),(22,1)):
        struct.pack_into('<H',raw,offset,value)
    raw[13]=1;raw[16]=2;raw[28:36]=bytes(8);raw[54:62]=b'FAT12   '
    raw[i.APP:i.APP+len(image)]=image
    return bytes(raw)


class FakeDevice:
    def __init__(self,raw,fail_at=None,corrupt=False):
        self.raw=bytearray(raw);self.writes=[];self.fail_at=fail_at;self.corrupt=corrupt;self.flushes=0
    def read(self,offset,count):return bytes(self.raw[offset:offset+count])
    def write(self,offset,data):
        if len(self.writes)==self.fail_at:raise OSError('injected transfer failure')
        self.writes.append(offset);self.raw[offset:offset+len(data)]=data
        if self.corrupt:self.raw[offset]^=1
    def flush(self):self.flushes+=1


class IdentityTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows ctypes ABI')
    def test_elevation_uses_hidden_worker_with_quoted_job_path(self):
        shell=mock.Mock();seen={}
        def execute(pointer):
            info=pointer._obj
            seen.update(verb=info.lpVerb,parameters=info.lpParameters,show=info.nShow,mask=info.fMask)
            info.hProcess=123
            return 1
        shell.ShellExecuteExW.side_effect=execute
        shell.CoInitializeEx.return_value=0
        with mock.patch.object(i.C,'WinDLL',return_value=shell):
            self.assertEqual(i.launch_elevated(Path('C:/local files/job')),123)
        self.assertEqual(seen['verb'],'runas');self.assertEqual(seen['show'],0)
        self.assertIn('--install-job "C:',seen['parameters'])
        self.assertEqual(seen['mask'],0x140)
        shell.CoUninitialize.assert_called_once()

    def test_locked_identity_uses_disk_and_pnp_not_mounted_volume(self):
        identity={'disk':4,'usb':'USB\\VID_0483&PID_5720\\TEST','serial':'TEST'}
        with mock.patch.object(i,'powershell',return_value='IDENTITY_OK') as query:
            i.verify_locked_identity(identity)
        script=query.call_args.args[0]
        self.assertIn('Get-Disk',script);self.assertIn('Get-PnpDevice',script)
        self.assertNotIn('Get-Volume',script);self.assertNotIn('Get-Partition',script)
        with mock.patch.object(i,'powershell',return_value='WRONG'):
            with self.assertRaises(ValueError):i.verify_locked_identity(identity)

    def test_ambiguous_missing_and_wrong_identity_are_refused(self):
        for data in ([],[{},{}],[{'letter':'C','disk':0,'usb':'USB\\OTHER','serial':'x'}]):
            with self.subTest(data=data),mock.patch.object(i,'powershell',return_value=json.dumps(data)):
                with self.assertRaises(ValueError):i.discover()
    def test_valid_identity_is_not_assumed_to_be_drive_e(self):
        identity={'letter':'G','disk':4,'usb':'USB\\VID_0483&PID_5720\\TEST','serial':'TEST'}
        with mock.patch.object(i,'powershell',return_value=json.dumps([identity])):
            self.assertEqual(i.discover(),identity)
    def test_geometry_refuses_any_unverified_mapping(self):
        raw=raw_fixture(b'')
        i.validate_geometry(raw)
        for offset in (11,13,14,16,17,19,22,28,32,54,510):
            changed=bytearray(raw);changed[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):i.validate_geometry(changed)


@unittest.skipUnless(os.environ.get('DDF350_OFFICIAL_FIRMWARE'),'local official input not supplied')
class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path(os.environ['DDF350_OFFICIAL_FIRMWARE']).read_bytes()
        p._require_original(cls.original)
        cls.target=p.build_patch(cls.original,usb_1ms=True,dashboard='custom',layout=json.loads(
            (Path(__file__).parents[1]/'examples/drift-six.json').read_text()))

    def test_all_supported_current_variants_and_custom_can_be_replaced(self):
        images=[self.original,self.target]+[p.build_patch(self.original,dashboard=d,usb_1ms=f)
            for d in ('original','ch1234','ch123456') for f in (False,True)]
        for image in images:
            with self.subTest(sha=p.sha256(image)):
                before=raw_fixture(image)
                after,offsets,_=i.plan_transfer(before,self.target,self.original)
                self.assertEqual(after[:i.APP],before[:i.APP])
                self.assertEqual(after[i.APP:i.APP+len(self.target)],self.target)
                self.assertEqual(after[i.APP+len(self.target):],before[i.APP+len(self.target):])
                self.assertEqual(offsets,tuple(sorted(offsets,reverse=True)))

    def test_success_saves_before_writes_and_checks_every_sector(self):
        before=raw_fixture(self.original);dev=FakeDevice(before)
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            i.transfer(dev,self.target,self.original,directory,lambda *a:None)
            self.assertEqual((directory/'avant-raw.bin').read_bytes(),before)
            self.assertEqual(dev.raw[i.APP:i.APP+len(self.target)],self.target)
            self.assertEqual(dev.flushes,len(dev.writes))
            self.assertEqual(dev.writes,sorted(dev.writes,reverse=True))

    def test_each_sector_failure_stops_without_retry_or_rollback(self):
        before=raw_fixture(self.original)
        _,offsets,_=i.plan_transfer(before,self.target,self.original)
        for failure in range(len(offsets)):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                dev=FakeDevice(before,fail_at=failure)
                with self.assertRaises(OSError):i.transfer(dev,self.target,self.original,Path(folder),lambda *a:None)
                self.assertEqual(dev.writes,list(offsets[:failure]))
                self.assertEqual(dev.raw[:i.APP],before[:i.APP])

    def test_unknown_current_or_corrupt_target_never_write(self):
        for current,target in ((b'unknown',self.target),(self.original,self.target[:-1]+b'x')):
            with tempfile.TemporaryDirectory() as folder:
                dev=FakeDevice(raw_fixture(current))
                with self.assertRaises(ValueError):i.transfer(dev,target,self.original,Path(folder),lambda *a:None)
                self.assertEqual(dev.writes,[])

    def test_failed_backup_prevents_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);(directory/'avant-raw.bin').write_bytes(b'preserve')
            dev=FakeDevice(raw_fixture(self.original))
            with self.assertRaises(FileExistsError):i.transfer(dev,self.target,self.original,directory,lambda *a:None)
            self.assertEqual(dev.writes,[])

    def test_readback_mismatch_stops_after_first_write(self):
        with tempfile.TemporaryDirectory() as folder:
            dev=FakeDevice(raw_fixture(self.original),corrupt=True)
            with self.assertRaises(ValueError):i.transfer(dev,self.target,self.original,Path(folder),lambda *a:None)
            self.assertEqual(len(dev.writes),1)

    def test_worker_retains_lock_until_two_confirmed_disconnects_on_success_and_failure(self):
        identity={'letter':'G','disk':4,'usb':'USB\\VID_0483&PID_5720\\TEST','serial':'TEST'}
        for failure in (None,OSError('injected write error')):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);directory=root/'job';directory.mkdir()
                (directory/'target.bin').write_bytes(self.target)
                (directory/'job.json').write_text(json.dumps({'identity':identity,'target_sha256':p.sha256(self.target)}))
                dev=mock.Mock();dev.locked=True
                events=[]
                def presence(*args):events.append('query');return '0'
                def closed():events.append('close')
                dev.close.side_effect=closed
                with mock.patch.object(i,'runs_root',return_value=root), \
                     mock.patch.object(i,'discover',return_value=identity), \
                     mock.patch.object(i,'verify_locked_identity'), \
                     mock.patch.object(i,'WindowsVolume',return_value=dev), \
                     mock.patch.object(i,'transfer',side_effect=failure), \
                     mock.patch.object(i,'powershell',side_effect=presence), \
                     mock.patch.object(i.time,'sleep'):
                    i.run_job(directory,self.original)
                self.assertEqual(events,['query','query','close'])
                self.assertEqual(json.loads((directory/'status.json').read_text())['phase'],'error' if failure else 'done')

    def test_identity_change_after_lock_prevents_transfer_and_retains_lock(self):
        identity={'letter':'G','disk':4,'usb':'USB\\VID_0483&PID_5720\\TEST','serial':'TEST'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'job';directory.mkdir()
            (directory/'target.bin').write_bytes(self.target)
            (directory/'job.json').write_text(json.dumps({'identity':identity,'target_sha256':p.sha256(self.target)}))
            dev=mock.Mock();dev.locked=True
            with mock.patch.object(i,'runs_root',return_value=root), \
                 mock.patch.object(i,'discover',return_value=identity), \
                 mock.patch.object(i,'verify_locked_identity',side_effect=ValueError('changed identity')), \
                 mock.patch.object(i,'WindowsVolume',return_value=dev), \
                 mock.patch.object(i,'transfer') as transfer, \
                 mock.patch.object(i,'powershell',return_value='0') as query, \
                 mock.patch.object(i.time,'sleep'):
                i.run_job(directory,self.original)
            transfer.assert_not_called();self.assertEqual(query.call_count,2);dev.close.assert_called_once()


if __name__=='__main__':unittest.main()
