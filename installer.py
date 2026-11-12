"""Explicit Windows maintenance transfer. No hardware access on import.

Only the audited 247 x 4096-byte maintenance mapping is supported. A locked
volume is retained until physical USB removal, including failures. The pure
planner and injected transport allow offline fault tests without a radio.
"""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
from datetime import datetime
import traceback

import patch_firmware as p
import dashboard_custom as custom
import startup_animation as startup

RAW_SIZE, SECTOR, APP = 1011712, 4096, 0x7000
LEGACY_SIZE = 828760
LEGACY_HASH = 'c1c913dec0e395ccfb7c4dc8e71a4b1d3d8da9242a635cdffe979fc44208b77d'
LEGACY_TAIL = 'ae5a309a9ebb500976a7d2fe69155a308768972faf87c50d73bbc32ad1043cf7'


def require(ok, text):
    if not ok:
        raise ValueError(text)


def validate_geometry(raw):
    require(len(raw) == RAW_SIZE, 'Taille de mémoire non prise en charge.')
    require(raw[510:512] == b'\x55\xaa' and
            struct.unpack_from('<H', raw, 11)[0] == SECTOR and raw[13] == 1 and
            struct.unpack_from('<H', raw, 14)[0] == 1 and raw[16] == 2 and
            struct.unpack_from('<H', raw, 17)[0] == 512 and
            struct.unpack_from('<H', raw, 19)[0] == 247 and
            struct.unpack_from('<H', raw, 22)[0] == 1 and
            raw[28:36] == bytes(8) and raw[54:62] == b'FAT12   ',
            'Géométrie du mode maintenance inconnue.')


def known_svi(raw):
    """Recognize the audited Windows prefix with either file-entry order.

    Windows can create the WPSettings and IndexerVolumeGuid entries in either
    order, independently of their cluster allocation. All non-timestamp bytes
    and both payload structures remain constrained; no generic prefix skip.
    """
    if len(raw) != RAW_SIZE:
        return False
    template = bytearray.fromhex(
        '2e2020202020202020202010005146b75f5d5f5d000047b75f5d020000000000'
        '2e2e20202020202020202010005146b75f5d5f5d000047b75f5d000000000000'
        '4274000000ffffffffffff0f00ceffffffffffffffffffffffff0000ffffffff'
        '01570050005300650074000f00ce740069006e00670073002e00000064006100'
        '5750534554547e3144415420006346b75f5d5f5d000047b75f5d03000c000000'
        '42470075006900640000000f00ffffffffffffffffffffffffff0000ffffffff'
        '0149006e006400650078000f00ff6500720056006f006c00750000006d006500'
        '494e444558457e3120202020001f47b75f5d5f5d000048b75f5d04004c000000')
    if raw[0x7080:0x708b] == b'INDEXE~1   ':
        # Swap the complete 3-entry LFN/SFN groups, not just short names.
        template[0x40:0x100] = template[0xa0:0x100] + template[0x40:0xa0]
        wp_entry, guid_entry = 0xe0, 0x80
    else:
        wp_entry, guid_entry = 0x80, 0xe0
    wp, guid = (struct.unpack_from('<H', raw, APP+n+26)[0] for n in (wp_entry, guid_entry))
    if {wp, guid} != {3, 4}:
        return False
    template[wp_entry+26], template[guid_entry+26] = wp, guid
    for i, byte in enumerate(template):
        entry, within = divmod(i, 32)
        timestamp = entry in (0, 1, 4, 7) and (13 <= within <= 19 or 22 <= within <= 25)
        if not timestamp and raw[APP+i] != byte:
            return False
    a, b = APP+(wp-2)*SECTOR, APP+(guid-2)*SECTOR
    try:
        text = raw[b:b+76].decode('utf-16le')
    except UnicodeError:
        return False
    return (raw[0x7100:0x8000] == bytes(0xf00) and
            struct.unpack_from('<I', raw, a)[0] == 12 and
            raw[a+12:a+SECTOR] == bytes(SECTOR-12) and
            raw[b+76:b+SECTOR] == bytes(SECTOR-76) and
            re.fullmatch(r'\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}', text) is not None)


def recognize_installed(raw, original):
    validate_geometry(raw)
    p._require_original(original)
    app = raw[APP:]
    legacy = app[:LEGACY_SIZE]
    if p.sha256(legacy) == LEGACY_HASH:
        return 'legacy-usb1ms'
    damaged = known_svi(raw)
    if damaged and p.sha256(legacy[0x3000:]) == LEGACY_TAIL:
        return 'legacy-usb1ms/windows-prefix'
    candidates = [original] + [p.build_patch(original, dashboard=d, usb_1ms=f)
        for d in ('original','ch1234','ch123456') for f in (False,True)]
    # Custom trailer is bounded by the generator; complete regeneration verifies it.
    # Search the known metadata windows, not user-controlled photo pixels.
    for start,limit in ((p.ORIGINAL_SIZE,startup.PLAYER_OFFSET),(custom.wallpaper.END,p.MAX_CUSTOM_IMAGE_SIZE)):
        pos=app.find(custom.TRAILER_MAGIC,start,limit)
        if pos==-1:continue
        end = pos + len(custom.TRAILER_MAGIC)
        try:
            layout, fast = custom.read_trailer(app[:end])
            candidates.append(p.build_patch(original, dashboard='custom', usb_1ms=fast, layout=layout))
        except (ValueError, TypeError, KeyError):
            pass
    photo=p.photo
    if app[photo.HOOK:photo.HOOK+4]==photo.BRANCH:
        image=app[:photo.END]
        if damaged:image=original[:0x3000]+image[0x3000:]
        info=p.inspect_image(image)
        if info.get('startup_photo'):
            return info['variant']+('/windows-prefix' if damaged else '')
        raise ValueError('Photo de démarrage ou firmware non reconnu.')
    asset_ptr,asset_len=struct.unpack_from('<II',app,startup.PLAYER_OFFSET+4)
    asset_end=asset_ptr-startup.BASE+asset_len
    pos=(app.find(startup.TRAILER_MAGIC,asset_end,min(p.MAX_IMAGE_SIZE,asset_end+1024+4+len(startup.TRAILER_MAGIC)))
         if 52<=asset_len<=startup.MAX_ASSET_SIZE and startup.PLAYER_OFFSET<asset_end<p.MAX_IMAGE_SIZE else -1)
    if pos!=-1:
        end=pos+len(startup.TRAILER_MAGIC)
        try:
            # Reconstruct from pinned stock, never from the raw radio prefix.
            # The exact Windows SVI exception below is applied only afterward.
            base,asset,player_version=startup.unpack(app[:end],with_version=True)
            base_info=p.inspect_image(base)
            if not base_info['recognized'] and damaged:
                base=original[:0x3000]+base[0x3000:]
                base_info=p.inspect_image(base)
            if base_info['recognized']:
                candidates.append(p.build_patch(original,dashboard=base_info['dashboard'],
                    usb_1ms='usb1ms' in base_info['variant'],layout=base_info.get('layout'),startup_animation=asset,
                    startup_player_version=player_version))
        except (ValueError,TypeError,KeyError,struct.error):
            pass
    for expected in candidates:
        if app[:len(expected)] == expected:
            return p.inspect_image(expected)['variant']
        if damaged and app[0x3000:len(expected)] == expected[0x3000:]:
            return p.inspect_image(expected)['variant'] + '/windows-prefix'
    raise ValueError('Firmware installé inconnu. Sauvegarde conservée ; aucun transfert autorisé.')


def validate_new_target(target):
    info=p.inspect_image(target)
    require(info['recognized'],'Cible modifiée ou inconnue.')
    if info.get('startup_animation'):
        from startup_media import validate_new_animation
        _,asset,version=startup.unpack(target,with_version=True)
        require(version==2,'Ancien lecteur de démarrage : prépare un nouveau fichier.')
        validate_new_animation(asset)


def plan_transfer(before, target, original):
    require(p.inspect_image(target)['recognized'], 'Fichier cible non reconnu.')
    state = recognize_installed(before, original)
    after = bytearray(before)
    after[APP:APP+len(target)] = target
    require(len(after) == RAW_SIZE, 'Cible hors mémoire application.')
    offsets = tuple(i for i in range(RAW_SIZE-SECTOR, APP-1, -SECTOR)
                    if before[i:i+SECTOR] != after[i:i+SECTOR])
    return bytes(after), offsets, state


def transfer(device, target, original, directory, notify):
    """Device already exclusively locked. Never unlock or close it here."""
    notify('checking','Lecture de la mémoire pour la sauvegarde…')
    before = device.read(0, RAW_SIZE)
    backup = directory / 'avant-raw.bin'
    with backup.open('xb') as f:
        f.write(before); f.flush(); os.fsync(f.fileno())
    require(backup.read_bytes() == before, 'Sauvegarde locale différente.')
    notify('checking','Sauvegarde enregistrée et vérifiée sur le PC.')
    after, offsets, state = plan_transfer(before, target, original)
    notify('checking',f'Firmware installé reconnu : {state}. {len(offsets)} blocs à transférer.')
    with (directory/'plan.json').open('x',encoding='utf-8') as f:
        json.dump({'installed':state, 'target_sha256':p.sha256(target),
                   'backup_sha256':p.sha256(before), 'offsets':offsets},f)
    for count, offset in enumerate(offsets):
        require(device.read(offset, SECTOR) == before[offset:offset+SECTOR], 'Mémoire modifiée depuis la sauvegarde.')
        device.write(offset, after[offset:offset+SECTOR])
        device.flush()
        require(device.read(offset, SECTOR) == after[offset:offset+SECTOR], 'Relecture du transfert différente. Arrêt.')
        notify('writing', f'Transfert : {count+1} / {len(offsets)} blocs vérifiés')
    notify('checking','Relecture finale de toute la mémoire…')
    require(device.read(0, RAW_SIZE) == after, 'Contrôle final de la mémoire différent.')


DISCOVERY = r'''
$ErrorActionPreference='Stop'
$found=@(foreach($v in @(Get-Volume | Where-Object FileSystemLabel -eq 'DUMBORC')) {
 if(-not $v.DriveLetter -or $v.FileSystemType -ne 'FAT' -or $v.Size -ne 983040){continue}
 $parts=@(Get-Partition -DriveLetter $v.DriveLetter)
 if($parts.Count -ne 1){continue}; $part=$parts[0]; $d=Get-Disk -Number $part.DiskNumber
 if($d.BusType -ne 'USB' -or $d.Size -ne 1011712 -or $d.LogicalSectorSize -ne 4096 -or $part.Offset -ne 0 -or $part.Size -ne 1011712){continue}
 $dd=Get-CimInstance Win32_DiskDrive -Filter ('Index='+$d.Number)
 $id=$dd.PNPDeviceID; $usb=$null
 for($i=0;$i -lt 8 -and $id;$i++) {
  if($id -match '^USB\\VID_0483&PID_5720\\[^\\]+$'){$usb=$id;break}
  $id=(Get-PnpDeviceProperty -InstanceId $id -KeyName 'DEVPKEY_Device_Parent' -ErrorAction Stop).Data
 }
 if($usb){[pscustomobject]@{letter=[string]$v.DriveLetter;disk=[int]$d.Number;usb=[string]$usb;serial=[string]$d.SerialNumber.Trim()}}
})
ConvertTo-Json -InputObject $found -Compress
'''


def powershell(script):
    require(sys.platform == 'win32', 'Installation disponible sur Windows uniquement.')
    executable = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    return subprocess.run([str(executable),'-NoProfile','-NonInteractive','-Command',script],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=35,
        creationflags=subprocess.CREATE_NO_WINDOW, check=True).stdout.strip()


def discover():
    data = json.loads(powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"+DISCOVERY) or '[]')
    require(type(data) is list and len(data) == 1, 'Branche une seule DDF-350 en mode mise à jour, puis réessaie.')
    item = data[0]
    require(set(item) == {'letter','disk','usb','serial'} and re.fullmatch('[A-Z]',item['letter']) and
            type(item['disk']) is int and item['disk'] >= 0 and
            re.fullmatch(r'USB\\VID_0483&PID_5720\\[^\\]+', item['usb'], re.I), 'Identification USB incohérente.')
    return item


def verify_locked_identity(identity):
    """Never query the mounted filesystem after FSCTL_LOCK_VOLUME."""
    require(type(identity['disk']) is int and identity['disk']>=0,'Numéro de disque incorrect.')
    usb=identity['usb'].replace("'","''")
    serial=identity['serial'].replace("'","''")
    script=("$ErrorActionPreference='Stop'; $d=Get-Disk -Number "+str(identity['disk'])+
        "; $u=Get-PnpDevice -PresentOnly -InstanceId '"+usb+"'; "+
        "if($u.Status -eq 'OK' -and $d.BusType -eq 'USB' -and $d.Size -eq 1011712 "+
        "-and $d.LogicalSectorSize -eq 4096 -and $d.SerialNumber.Trim() -eq '"+serial+
        "'){ 'IDENTITY_OK' } else { throw 'USB identity changed' }")
    require(powershell(script)=='IDENTITY_OK','Identification USB modifiée après verrouillage.')


class WindowsVolume:
    def __init__(self, identity):
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.k.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
        self.k.CreateFileW.restype=W.HANDLE
        self.k.DeviceIoControl.argtypes=[W.HANDLE,W.DWORD,C.c_void_p,W.DWORD,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]
        self.k.SetFilePointerEx.argtypes=[W.HANDLE,C.c_longlong,C.c_void_p,W.DWORD]
        self.k.ReadFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]
        self.k.WriteFile.argtypes=self.k.ReadFile.argtypes
        self.k.FlushFileBuffers.argtypes=[W.HANDLE]
        self.k.CloseHandle.argtypes=[W.HANDLE]
        self.handle=self.k.CreateFileW('\\\\.\\'+identity['letter']+':',0xc0000000,3,None,3,0,None)
        if self.handle == W.HANDLE(-1).value:
            raise C.WinError(C.get_last_error())
        self.locked=False
        try:
            info=C.create_string_buffer(12); n=W.DWORD()
            if not self.k.DeviceIoControl(self.handle,0x2d1080,None,0,info,12,C.byref(n),None):
                raise C.WinError(C.get_last_error())
            require(n.value==12 and struct.unpack('<III',info.raw)[1]==identity['disk'], 'Disque USB remplacé.')
            if not self.k.DeviceIoControl(self.handle,0x90018,None,0,None,0,C.byref(n),None):
                raise OSError('Accès exclusif refusé. Ferme les fenêtres ouvertes sur la radio, puis réessaie.')
            self.locked=True
        except Exception:
            self.close(); raise

    def read(self, offset, count):
        require(offset >= 0 and count > 0 and offset+count <= RAW_SIZE and offset%SECTOR==0 and count%SECTOR==0,'Lecture hors profil.')
        if count > SECTOR:
            return b''.join(self.read(i,SECTOR) for i in range(offset,offset+count,SECTOR))
        self.seek(offset); buf=C.create_string_buffer(count); n=W.DWORD()
        if not self.k.ReadFile(self.handle,buf,count,C.byref(n),None) or n.value!=count:
            raise OSError('Lecture USB incomplète.')
        return buf.raw

    def seek(self, offset):
        if not self.k.SetFilePointerEx(self.handle,offset,None,0):
            raise C.WinError(C.get_last_error())

    def write(self, offset, data):
        require(self.locked and offset >= APP and offset%SECTOR==0 and len(data)==SECTOR and offset+SECTOR<=RAW_SIZE,'Écriture hors profil.')
        self.seek(offset); n=W.DWORD(); buf=C.create_string_buffer(data)
        if not self.k.WriteFile(self.handle,buf,len(data),C.byref(n),None) or n.value!=len(data):
            raise OSError('Transfert USB incomplet. Garde la radio éteinte.')

    def flush(self):
        if not self.k.FlushFileBuffers(self.handle):
            raise C.WinError(C.get_last_error())

    def allow_partition_reads(self):
        n=W.DWORD()
        if not self.k.DeviceIoControl(self.handle,0x90083,None,0,None,0,C.byref(n),None):
            raise C.WinError(C.get_last_error())

    def close(self):
        self.k.CloseHandle(self.handle)


def status(directory, phase, message):
    require(directory.resolve().is_relative_to(runs_root().resolve()),'Compte rendu hors application.')
    tmp=directory/'status.tmp'
    with tmp.open('x',encoding='utf-8') as f:
        json.dump({'phase':phase,'message':message},f)
    os.replace(tmp,directory/'status.json')
    append_log(directory,phase,message)


def append_log(directory, phase, message, *, filename='journal.jsonl'):
    require(filename in ('journal.jsonl','interface.jsonl'),'Nom de journal incorrect.')
    require(directory.resolve().is_relative_to(runs_root().resolve()),'Journal hors application.')
    record={'time':datetime.now().astimezone().isoformat(timespec='seconds'),'phase':phase,'message':str(message)}
    with (directory/filename).open('a',encoding='utf-8') as f:
        f.write(json.dumps(record,ensure_ascii=False)+'\n')


def runs_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'DDF350-USB-Toolkit' / 'installations'


def run_job(directory, original=None):
    directory=p.validate_local_path(directory,output=True)
    p._check_local_volume(directory,'Installation backup')
    require(directory.is_relative_to(runs_root()) and directory.resolve().is_relative_to(runs_root().resolve()),'Dossier de transfert hors application.')
    for path in (directory,*directory.parents):
        require(not (path.lstat().st_file_attributes & 1024),'Dossier de transfert redirigé.')
    if original is None:
        original=p.read_regular_file(directory/'original.bin')
    p._require_original(original)
    jobpath=directory/'job.json'
    require(jobpath.is_file() and not jobpath.is_symlink() and jobpath.stat().st_size<=4096,'Demande incorrecte.')
    job=json.loads(jobpath.read_text(encoding='utf-8'))
    require(set(job)=={'identity','target_sha256'},'Demande incorrecte.')
    target=p.read_regular_file(directory/'target.bin')
    require(p.sha256(target)==job['target_sha256'],'Cible modifiée ou inconnue.')
    validate_new_target(target)
    require(discover()==job['identity'],'La radio détectée a changé. Recommence la connexion.')
    device=None; failure=None
    notify=lambda phase,message:status(directory,phase,message)
    try:
        notify('checking','Processus administrateur démarré. Demande d’accès exclusif…')
        device=WindowsVolume(job['identity'])
        notify('checking','Volume USB verrouillé. Contrôle de l’identité du disque…')
        device.allow_partition_reads()
        verify_locked_identity(job['identity'])
        notify('checking','Identité USB confirmée, accès protégé prêt.')
        transfer(device,target,original,directory,notify)
        notify('unplug','Installation vérifiée. Débranche maintenant le câble USB.')
    except Exception as error:
        failure=str(error)
        try: append_log(directory,'diagnostic',traceback.format_exc())
        except OSError: pass
        notify('error_unplug' if device and device.locked else 'error',
               failure+(' Débranche maintenant l’USB ; garde la radio éteinte.' if device and device.locked else ''))
    finally:
        if device and device.locked:
            # Never release a mounted Windows FAT view over application flash.
            absent=0
            usb=job['identity']['usb'].replace("'","''")
            while absent<2:
                time.sleep(1)
                try:
                    result=powershell("$ErrorActionPreference='Stop'; @(Get-PnpDevice -PresentOnly | Where-Object InstanceId -eq '"+usb+"').Count")
                    absent=absent+1 if result=='0' else 0
                except Exception:
                    absent=0
            device.close()
            notify('error' if failure else 'done',failure or 'Transfert terminé. Rallume la radio avec Power uniquement.')
        elif device:
            device.close()


def launch_elevated(directory):
    """Same application, hidden elevated worker, retained process handle."""
    require(sys.platform=='win32','Windows requis.')
    class ExecuteInfo(C.Structure):
        _fields_=[('cbSize',W.DWORD),('fMask',C.c_ulong),('hwnd',W.HWND),('lpVerb',W.LPCWSTR),
            ('lpFile',W.LPCWSTR),('lpParameters',W.LPCWSTR),('lpDirectory',W.LPCWSTR),('nShow',C.c_int),
            ('hInstApp',W.HINSTANCE),('lpIDList',C.c_void_p),('lpClass',W.LPCWSTR),('hkeyClass',W.HKEY),
            ('dwHotKey',W.DWORD),('hIcon',W.HANDLE),('hProcess',W.HANDLE)]
    args=['--install-job',str(directory)]
    if not getattr(sys,'frozen',False):
        args.insert(0,str(Path(__file__).with_name('app.py')))
    info=ExecuteInfo();info.cbSize=C.sizeof(info);info.fMask=0x140
    info.lpVerb='runas';info.lpFile=sys.executable;info.lpParameters=subprocess.list2cmdline(args);info.nShow=0
    ole=C.WinDLL('ole32',use_last_error=True)
    ole.CoInitializeEx.argtypes=[C.c_void_p,W.DWORD]
    ole.CoInitializeEx.restype=C.c_long
    initialized=ole.CoInitializeEx(None,6)
    if initialized not in (0,1):
        raise OSError(f'Initialisation de la demande Windows impossible : {initialized:#x}')
    shell=C.WinDLL('shell32',use_last_error=True)
    shell.ShellExecuteExW.argtypes=[C.POINTER(ExecuteInfo)]
    try:
        if not shell.ShellExecuteExW(C.byref(info)):
            code=C.get_last_error()
            raise OSError(code,'Demande Windows annulée.' if code==1223 else f'Lancement administrateur impossible : {C.FormatError(code)}')
        require(bool(info.hProcess),'Windows n’a pas renvoyé le processus d’installation.')
        return info.hProcess
    finally:
        ole.CoUninitialize()


def worker_active(handle):
    k=C.WinDLL('kernel32',use_last_error=True);code=W.DWORD()
    k.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
    if not k.GetExitCodeProcess(handle,C.byref(code)):
        raise C.WinError(C.get_last_error())
    return code.value==259


def close_process(handle):
    k=C.WinDLL('kernel32',use_last_error=True);k.CloseHandle.argtypes=[W.HANDLE];k.CloseHandle(handle)
