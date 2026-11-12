"""Read-only Windows HID viewer for the exact DDF-350 0483:5750 report.

Importing this module neither enumerates devices nor opens a window. Running main() explicitly opens the read-only viewer. Standard library only.
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import os
import queue
import struct
import threading
import time

VID, PID = 0x0483, 0x5750
REPORT_BYTES = 18
CENTER, MAX_VALUE = 1023, 2047
STALE_SECONDS = 1.0


@dataclass(frozen=True)
class Channels:
    ch1: int
    ch2: int


def decode_report(report: bytes) -> Channels:
    """Decode only CH1/CH2; Windows supplies zero report-ID +17 native bytes.

    Byte1 contains buttons; bytes2..3 and4..5 are little-endian channel values.
    This matches the native firmware report (buttons first, then eight axes).
    No calibration,
    rescaling, interpolation, synthetic value or guessed HID field is applied.
    The remaining six axes and button byte are deliberately not interpreted.
    """
    if not isinstance(report, (bytes, bytearray, memoryview)):
        raise TypeError('Un rapport doit contenir des octets.')
    report = bytes(report)
    if len(report) != REPORT_BYTES:
        raise ValueError(f'Longueur reçue : {len(report)} octets ; 18 attendus.')
    if report[0] != 0:
        raise ValueError('Identifiant de rapport inattendu : zéro attendu.')
    ch1, ch2 = struct.unpack_from('<HH', report, 2)
    if not (0 <= ch1 <= MAX_VALUE and 0 <= ch2 <= MAX_VALUE):
        raise ValueError('Valeur CH1 ou CH2 hors de la plage 0 à 2047.')
    return Channels(ch1, ch2)


# Fixed Windows ABI widths, including when this module is only imported elsewhere.
DWORD, WORD, BOOL, HANDLE = C.c_uint32, C.c_uint16, C.c_int32, C.c_void_p
INVALID_HANDLE = C.c_void_p(-1).value
GENERIC_READ, SHARE_READ_WRITE = 0x80000000, 3
OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 3, 0x40000000
ERROR_INSUFFICIENT_BUFFER, ERROR_NO_MORE_ITEMS = 122, 259
ERROR_IO_PENDING, ERROR_OPERATION_ABORTED = 997, 995
WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED = 0, 258, 0xffffffff
HIDP_STATUS_SUCCESS = 0x00110000


class GUID(C.Structure):
    _fields_ = [('Data1',DWORD),('Data2',WORD),('Data3',WORD),('Data4',C.c_ubyte*8)]


class INTERFACE_DATA(C.Structure):
    _fields_ = [('cbSize',DWORD),('InterfaceClassGuid',GUID),('Flags',DWORD),('Reserved',C.c_size_t)]


class DEVINFO_DATA(C.Structure):
    _fields_ = [('cbSize',DWORD),('ClassGuid',GUID),('DevInst',DWORD),('Reserved',C.c_size_t)]


class HIDD_ATTRIBUTES(C.Structure):
    _fields_ = [('Size',DWORD),('VendorID',WORD),('ProductID',WORD),('VersionNumber',WORD)]


class HIDP_CAPS(C.Structure):
    _fields_ = [('Usage',WORD),('UsagePage',WORD),('InputReportByteLength',WORD),
        ('OutputReportByteLength',WORD),('FeatureReportByteLength',WORD),('Reserved',WORD*17),
        ('NumberLinkCollectionNodes',WORD),('NumberInputButtonCaps',WORD),
        ('NumberInputValueCaps',WORD),('NumberInputDataIndices',WORD),
        ('NumberOutputButtonCaps',WORD),('NumberOutputValueCaps',WORD),
        ('NumberOutputDataIndices',WORD),('NumberFeatureButtonCaps',WORD),
        ('NumberFeatureValueCaps',WORD),('NumberFeatureDataIndices',WORD)]


class OVERLAPPED(C.Structure):
    _fields_ = [('Internal',C.c_size_t),('InternalHigh',C.c_size_t),
                ('Offset',DWORD),('OffsetHigh',DWORD),('hEvent',HANDLE)]


@dataclass(frozen=True)
class Device:
    path: str
    version: int


class WindowsHid:
    """Small native API adapter. No write/report-control API is bound."""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Ce lecteur nécessite Windows.')
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.setup = C.WinDLL('setupapi', use_last_error=True)
        self.hid = C.WinDLL('hid', use_last_error=True)
        def bind(dll, name, args, result):
            fn = getattr(dll, name); fn.argtypes=args; fn.restype=result
            return fn
        ptr = C.c_void_p
        self.CreateFile = bind(self.kernel,'CreateFileW',
            [C.c_wchar_p,DWORD,DWORD,ptr,DWORD,DWORD,HANDLE],HANDLE)
        self.CloseHandle = bind(self.kernel,'CloseHandle',[HANDLE],BOOL)
        self.ReadFile = bind(self.kernel,'ReadFile',[HANDLE,ptr,DWORD,C.POINTER(DWORD),C.POINTER(OVERLAPPED)],BOOL)
        self.CancelIoEx = bind(self.kernel,'CancelIoEx',[HANDLE,ptr],BOOL)
        self.GetOverlappedResult = bind(self.kernel,'GetOverlappedResult',
            [HANDLE,C.POINTER(OVERLAPPED),C.POINTER(DWORD),BOOL],BOOL)
        self.CreateEvent = bind(self.kernel,'CreateEventW',[ptr,BOOL,BOOL,C.c_wchar_p],HANDLE)
        self.ResetEvent = bind(self.kernel,'ResetEvent',[HANDLE],BOOL)
        self.WaitForSingleObject = bind(self.kernel,'WaitForSingleObject',[HANDLE,DWORD],DWORD)
        self.GetHidGuid = bind(self.hid,'HidD_GetHidGuid',[C.POINTER(GUID)],None)
        self.GetAttributes = bind(self.hid,'HidD_GetAttributes',[HANDLE,C.POINTER(HIDD_ATTRIBUTES)],C.c_ubyte)
        self.GetPreparsedData = bind(self.hid,'HidD_GetPreparsedData',[HANDLE,C.POINTER(ptr)],C.c_ubyte)
        self.FreePreparsedData = bind(self.hid,'HidD_FreePreparsedData',[ptr],C.c_ubyte)
        self.GetCaps = bind(self.hid,'HidP_GetCaps',[ptr,C.POINTER(HIDP_CAPS)],C.c_int32)
        self.GetClassDevs = bind(self.setup,'SetupDiGetClassDevsW',[C.POINTER(GUID),C.c_wchar_p,HANDLE,DWORD],HANDLE)
        self.EnumInterfaces = bind(self.setup,'SetupDiEnumDeviceInterfaces',
            [HANDLE,ptr,C.POINTER(GUID),DWORD,C.POINTER(INTERFACE_DATA)],BOOL)
        self.GetInterfaceDetail = bind(self.setup,'SetupDiGetDeviceInterfaceDetailW',
            [HANDLE,C.POINTER(INTERFACE_DATA),ptr,DWORD,C.POINTER(DWORD),C.POINTER(DEVINFO_DATA)],BOOL)
        self.GetRegistryProperty = bind(self.setup,'SetupDiGetDeviceRegistryPropertyW',
            [HANDLE,C.POINTER(DEVINFO_DATA),DWORD,C.POINTER(DWORD),ptr,DWORD,C.POINTER(DWORD)],BOOL)
        self.DestroyDeviceInfo = bind(self.setup,'SetupDiDestroyDeviceInfoList',[HANDLE],BOOL)

    @staticmethod
    def error():
        code = C.get_last_error()
        return OSError(code, C.FormatError(code).strip())

    def close(self, handle):
        if handle not in (None,0,INVALID_HANDLE): self.CloseHandle(handle)

    def open(self, path, reading=False):
        handle = self.CreateFile(path,GENERIC_READ if reading else 0,SHARE_READ_WRITE,
                                 None,OPEN_EXISTING,FILE_FLAG_OVERLAPPED if reading else 0,None)
        if handle == INVALID_HANDLE: raise self.error()
        return handle

    def identity(self, handle):
        attributes = HIDD_ATTRIBUTES(); attributes.Size=C.sizeof(attributes)
        if not self.GetAttributes(handle,C.byref(attributes)): raise self.error()
        if (attributes.VendorID,attributes.ProductID)!=(VID,PID):
            raise ValueError('Identité USB différente de la DDF-350 attendue.')
        preparsed = C.c_void_p()
        if not self.GetPreparsedData(handle,C.byref(preparsed)): raise self.error()
        try:
            caps=HIDP_CAPS()
            if self.GetCaps(preparsed,C.byref(caps))!=HIDP_STATUS_SUCCESS:
                raise ValueError('Description HID illisible.')
            if (caps.UsagePage,caps.Usage,caps.InputReportByteLength)!=(1,5,REPORT_BYTES):
                raise ValueError('Format de manette différent du rapport DDF-350 attendu.')
        finally:
            self.FreePreparsedData(preparsed)
        return attributes.VersionNumber

    def hardware_ids(self, devices, info):
        needed, kind = DWORD(), DWORD()
        self.GetRegistryProperty(devices,C.byref(info),1,C.byref(kind),None,0,C.byref(needed))
        if C.get_last_error()!=ERROR_INSUFFICIENT_BUFFER or not (2<=needed.value<=1048576):
            return []
        buffer=C.create_string_buffer(needed.value)
        if not self.GetRegistryProperty(devices,C.byref(info),1,C.byref(kind),buffer,len(buffer),C.byref(needed)):
            return []
        # SPDRP_HARDWAREID is REG_MULTI_SZ; this is registry data, not parsing a symbolic path.
        if kind.value!=7: return []
        return bytes(buffer.raw).decode('utf-16-le',errors='strict').rstrip('\0').split('\0')

    def find(self):
        guid=GUID(); self.GetHidGuid(C.byref(guid))
        devices=self.GetClassDevs(C.byref(guid),None,None,0x12)  # PRESENT|DEVICEINTERFACE
        if devices==INVALID_HANDLE: raise self.error()
        found, issues = [], []
        try:
            index=0
            while True:
                interface=INTERFACE_DATA(); interface.cbSize=C.sizeof(interface)
                if not self.EnumInterfaces(devices,None,C.byref(guid),index,C.byref(interface)):
                    if C.get_last_error()==ERROR_NO_MORE_ITEMS: break
                    raise self.error()
                index+=1
                needed=DWORD(); info=DEVINFO_DATA(); info.cbSize=C.sizeof(info)
                self.GetInterfaceDetail(devices,C.byref(interface),None,0,C.byref(needed),C.byref(info))
                if C.get_last_error()!=ERROR_INSUFFICIENT_BUFFER or not (6<=needed.value<=1048576):
                    continue
                # Filter registry IDs before opening any collection; 5720 is never opened.
                ids=self.hardware_ids(devices,info)
                if not any(s.upper().startswith('HID\\VID_0483&PID_5750') for s in ids): continue
                detail=C.create_string_buffer(needed.value)
                DWORD.from_buffer(detail).value=8 if C.sizeof(C.c_void_p)==8 else 6
                if not self.GetInterfaceDetail(devices,C.byref(interface),detail,len(detail),C.byref(needed),None):
                    continue
                path=C.wstring_at(C.addressof(detail)+4)
                handle=None
                try:
                    handle=self.open(path)
                    found.append(Device(path,self.identity(handle)))
                except (OSError,ValueError) as error:
                    issues.append(str(error))
                finally:
                    self.close(handle)
        finally:
            self.DestroyDeviceInfo(devices)
        return found, issues


class Reader(threading.Thread):
    def __init__(self, events):
        super().__init__(name='Lecture DDF-350',daemon=True)
        self.events=events; self.stop_event=threading.Event()
        self.handle_lock=threading.Lock(); self.handle=None; self.api=None

    def post(self, kind, value=None):
        event=(kind,value,time.monotonic())
        try: self.events.put_nowait(event)
        except queue.Full:
            try: self.events.get_nowait()
            except queue.Empty: pass
            try: self.events.put_nowait(event)
            except queue.Full: pass

    def request_stop(self):
        self.stop_event.set()
        with self.handle_lock:
            if self.api is not None and self.handle is not None:
                self.api.CancelIoEx(self.handle,None)

    def read_one(self, handle, event):
        api=self.api
        if not api.ResetEvent(event): raise api.error()
        overlapped=OVERLAPPED(); overlapped.hEvent=event
        buffer=C.create_string_buffer(REPORT_BYTES); received=DWORD()
        # On an overlapped handle, obtain the authoritative byte count from
        # GetOverlappedResult even if ReadFile completes immediately.
        success=api.ReadFile(handle,buffer,len(buffer),None,C.byref(overlapped))
        if not success:
            error=C.get_last_error()
            if error!=ERROR_IO_PENDING: raise OSError(error,C.FormatError(error).strip())
            while True:
                if self.stop_event.is_set():
                    api.CancelIoEx(handle,C.byref(overlapped))
                    # Retain buffer/OVERLAPPED until cancellation is acknowledged.
                    # This worker is a daemon; the UI never waits indefinitely.
                    api.GetOverlappedResult(handle,C.byref(overlapped),C.byref(received),True)
                    raise OSError(ERROR_OPERATION_ABORTED,'Lecture arrêtée.')
                wait=api.WaitForSingleObject(event,100)
                if wait==WAIT_TIMEOUT: continue
                if wait==WAIT_FAILED:
                    error=api.error()
                    api.CancelIoEx(handle,C.byref(overlapped))
                    api.GetOverlappedResult(handle,C.byref(overlapped),C.byref(received),True)
                    raise error
                if wait!=WAIT_OBJECT_0:
                    api.CancelIoEx(handle,C.byref(overlapped))
                    api.GetOverlappedResult(handle,C.byref(overlapped),C.byref(received),True)
                    raise OSError('Résultat d’attente Windows inattendu.')
                break
        if not api.GetOverlappedResult(handle,C.byref(overlapped),C.byref(received),False):
            raise api.error()
        return buffer.raw[:received.value]

    def run(self):
        try: self.api=WindowsHid()
        except Exception as error:
            self.post('error',str(error)); return
        while not self.stop_event.is_set():
            handle=event=None
            try:
                devices, issues=self.api.find()
                if not devices:
                    self.post('searching',issues[0] if issues else None)
                    self.stop_event.wait(1.0); continue
                if len(devices)!=1:
                    self.post('error','Plusieurs radios compatibles : n’en brancher qu’une.')
                    self.stop_event.wait(1.0); continue
                device=devices[0]; handle=self.api.open(device.path,reading=True)
                version=self.api.identity(handle)  # Recheck the actual read handle.
                event=self.api.CreateEvent(None,True,False,None)
                if not event: raise self.api.error()
                with self.handle_lock: self.handle=handle
                self.post('connected',version)
                while not self.stop_event.is_set():
                    report=self.read_one(handle,event)
                    try: values=decode_report(report)
                    except (ValueError,TypeError) as error:
                        self.post('invalid',str(error)); continue
                    self.post('data',values)
            except (OSError,ValueError) as error:
                if not self.stop_event.is_set(): self.post('disconnected',str(error))
            finally:
                with self.handle_lock:
                    self.handle=None
                    self.api.close(handle)
                self.api.close(event)
            self.stop_event.wait(0.75)


class Viewer:
    def __init__(self, parent=None):
        import tkinter as tk
        self.tk=tk; self.owns_root=parent is None
        self.root=tk.Tk() if parent is None else tk.Toplevel(parent)
        self.root.title('DDF-350 · CH1 et CH2'); self.root.geometry('640x435')
        self.root.minsize(520,420); self.root.configure(bg='#10161f')
        self.events=queue.Queue(maxsize=128); self.reader=Reader(self.events)
        self.connected=False; self.values=None; self.last_data=None; self.problem=None
        self.closed=False; self.total_reports=0; self.poll_id=None
        tk.Label(self.root,text='DDF-350',font=('Segoe UI',22,'bold'),bg='#10161f',fg='#f2f6fa').pack(anchor='w',padx=28,pady=(22,2))
        self.identity=tk.Label(self.root,text='En attente de la radio USB',font=('Segoe UI',10),bg='#10161f',fg='#9aa9bb')
        self.identity.pack(anchor='w',padx=30)
        self.panels=[]
        for title,color in [('CH1 · Direction','#47d7d0'),('CH2 · Gaz / frein','#bca1ff')]:
            panel=tk.Frame(self.root,bg='#192332'); panel.pack(fill='x',padx=28,pady=(14,0))
            top=tk.Frame(panel,bg='#192332'); top.pack(fill='x',padx=16,pady=(10,2))
            tk.Label(top,text=title,font=('Segoe UI',13),bg='#192332',fg='#d9e4f1').pack(side='left')
            number=tk.Label(top,text='—',font=('Segoe UI',25,'bold'),bg='#192332',fg='#7b899b'); number.pack(side='right')
            canvas=tk.Canvas(panel,height=23,bg='#192332',highlightthickness=0)
            canvas.pack(fill='x',padx=16,pady=(0,12))
            canvas.bind('<Configure>',lambda _event:self.paint())
            self.panels.append((number,canvas,color))
        tk.Label(self.root,text='Valeurs brutes : 0 à 2047  ·  Centre attendu : 1023',font=('Segoe UI',10),bg='#10161f',fg='#9aa9bb').pack(anchor='w',padx=30,pady=(12,8))
        self.status=tk.Label(self.root,text='Recherche de la radio…',font=('Segoe UI',11,'bold'),bg='#10161f',fg='#e4b95b',anchor='w',wraplength=570)
        self.status.pack(fill='x',padx=30)
        self.age=tk.Label(self.root,text='Aucune donnée reçue',font=('Segoe UI',10),bg='#10161f',fg='#9aa9bb',anchor='w')
        self.age.pack(fill='x',padx=30,pady=(5,16))
        self.root.protocol('WM_DELETE_WINDOW',self.close)

    def paint(self):
        fresh=self.connected and self.last_data is not None and time.monotonic()-self.last_data<STALE_SECONDS and not self.problem
        for index,(number,canvas,color) in enumerate(self.panels):
            value=None if self.values is None else (self.values.ch1,self.values.ch2)[index]
            number.configure(text='—' if value is None else str(value),fg=color if fresh else '#7b899b')
            canvas.delete('all'); width=max(1,canvas.winfo_width()); left,right=1,width-1
            canvas.create_rectangle(left,6,right,17,fill='#2c3a4e',outline='')
            center=left+(right-left)*CENTER/MAX_VALUE
            if value is not None:
                pos=left+(right-left)*value/MAX_VALUE
                canvas.create_rectangle(left,6,pos,17,fill=color if fresh else '#59697f',outline='')
                canvas.create_line(pos,3,pos,20,fill='#edf5ff' if fresh else '#7b899b',width=2)
            canvas.create_line(center,4,center,19,fill='#15202d',width=2)

    def poll(self):
        if self.closed: return
        for _ in range(256):
            try: kind,value,stamp=self.events.get_nowait()
            except queue.Empty: break
            if kind=='connected':
                self.connected=True; self.values=None; self.last_data=None; self.problem=None
                self.identity.configure(text='Identité vérifiée : DDF-350 · USB 0483:5750')
            elif kind=='data':
                if not self.connected:
                    self.identity.configure(text='Identité vérifiée : DDF-350 · USB 0483:5750')
                self.connected=True; self.values=value; self.last_data=stamp; self.problem=None
                self.total_reports+=1
            elif kind=='invalid': self.problem='Rapport rejeté : '+value
            elif kind in ('searching','disconnected','error'):
                self.connected=False
                self.identity.configure(text='En attente de la radio USB')
                self.problem=('Radio non détectée' if kind=='searching' and not value else
                              'Radio déconnectée' if kind=='disconnected' else str(value))
        now=time.monotonic()
        if self.problem:
            text=self.problem; color='#e4b95b'
        elif not self.connected:
            text='Recherche de la radio…'; color='#e4b95b'
        elif self.last_data is None:
            text='Radio connectée · en attente de données'; color='#e4b95b'
        elif now-self.last_data>=STALE_SECONDS:
            text='Données périmées · aucune nouvelle réception'; color='#e4b95b'
        else:
            text='Lecture en direct'; color='#63ddb5'
        self.status.configure(text=text,fg=color)
        self.age.configure(text='Aucune donnée reçue' if self.last_data is None else
                           f'Dernière donnée : il y a {max(0.0,now-self.last_data):.1f} s')
        self.paint(); self.poll_id=self.root.after(8,self.poll)

    def close(self):
        if self.closed: return
        self.closed=True; self.reader.request_stop()
        if self.poll_id is not None: self.root.after_cancel(self.poll_id)
        self.root.destroy()

    def run(self):
        self.reader.start(); self.poll()
        if not self.owns_root: return
        try: self.root.mainloop()
        finally: self.reader.request_stop()


def main():
    Viewer().run()


if __name__=='__main__':
    main()
