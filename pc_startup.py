"""Opt-in, per-user Windows startup. Importing only defines functions.

Only the PC-mode checkbox calls enable/disable. No service, driver, elevation,
device-trigger task or startup registration occurs during build/self-tests.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys

import patch_firmware as p

RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME='DDF350ToolkitPC'


def startup_folder():
    return Path(os.environ['LOCALAPPDATA'])/'DDF350-USB-Toolkit'/'startup'


def installed_executable():
    return Path(os.environ['LOCALAPPDATA'])/'Programs'/'DDF350 USB Toolkit'/'DDF350-USB-Toolkit.exe'


def registry():
    if sys.platform!='win32':raise OSError('Option disponible sur Windows uniquement.')
    import winreg
    return winreg


def managed_command(command):
    if not isinstance(command,str):return False
    installed=subprocess.list2cmdline([str(installed_executable()),'--pc-mode','--minimized'])
    if command.casefold()==installed.casefold():return True
    # Commands are generated only by list2cmdline below; no shell is involved.
    prefix=str(startup_folder())
    pattern=r'^"?'+re.escape(prefix)+r'[\\/]DDF350-PC-[0-9a-f]{12}\.exe"? --pc-mode --minimized$'
    return re.fullmatch(pattern,command,re.I) is not None


def current_command():
    reg=registry()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER,RUN_KEY,0,reg.KEY_READ) as key:
            value,kind=reg.QueryValueEx(key,VALUE_NAME)
    except FileNotFoundError:return None
    if kind!=reg.REG_SZ or not managed_command(value):
        raise OSError('Une entrée de démarrage différente porte déjà ce nom. Elle a été conservée.')
    return value


def is_enabled():
    return current_command() is not None


def stage_executable():
    if not getattr(sys,'frozen',False):
        raise OSError('Le démarrage automatique nécessite l’exécutable Windows compilé.')
    source=Path(sys.executable).resolve()
    payload=source.read_bytes()
    if not payload.startswith(b'MZ'):raise OSError('Exécutable Windows non reconnu.')
    digest=hashlib.sha256(payload).hexdigest()
    if source==installed_executable().resolve():
        p._check_local_volume(source,'Windows startup')
        return source
    folder=startup_folder()
    p._check_local_volume(folder,'Windows startup')
    for ancestor in (folder,*folder.parents):
        if ancestor.exists() and (getattr(ancestor.lstat(),'st_file_attributes',0)&1024):
            raise OSError('Destination de démarrage redirigée : opération refusée.')
    folder.mkdir(parents=True,exist_ok=True)
    destination=folder/f'DDF350-PC-{digest[:12]}.exe'
    try:
        with destination.open('xb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
    except FileExistsError:pass
    if destination.is_symlink() or hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
        raise OSError('La copie de démarrage est différente. Aucune inscription Windows effectuée.')
    return destination


def enable():
    current_command()  # Refuse to overwrite an unrelated value before copying.
    destination=stage_executable()
    command=subprocess.list2cmdline([str(destination),'--pc-mode','--minimized'])
    if len(command)>260:raise OSError('Chemin de démarrage trop long pour Windows.')
    reg=registry()
    with reg.CreateKeyEx(reg.HKEY_CURRENT_USER,RUN_KEY,0,reg.KEY_SET_VALUE) as key:
        reg.SetValueEx(key,VALUE_NAME,0,reg.REG_SZ,command)


def disable():
    if current_command() is None:return
    reg=registry()
    with reg.OpenKey(reg.HKEY_CURRENT_USER,RUN_KEY,0,reg.KEY_SET_VALUE) as key:
        try:reg.DeleteValue(key,VALUE_NAME)
        except FileNotFoundError:pass
