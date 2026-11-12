"""Native Windows notification icon with its own message-loop thread.

No USB access or startup changes. Commands are queued back to the Tk thread.
The hidden top-level window also receives Explorer's TaskbarCreated broadcast.
"""
import ctypes as C
from ctypes import wintypes as W
import math
import os
import queue
import threading
from i18n import tr

CALLBACK=0x8000+40
WM_CLOSE,WM_DESTROY,WM_NULL=0x10,2,0
WM_LBUTTONUP,WM_LBUTTONDBLCLK,WM_RBUTTONUP,WM_CONTEXTMENU=0x202,0x203,0x205,0x7b
UPDATE=CALLBACK+1


class GUID(C.Structure):
    _fields_=[('a',C.c_uint32),('b',C.c_uint16),('c',C.c_uint16),('d',C.c_ubyte*8)]


class NOTIFYICONDATA(C.Structure):
    _fields_=[('cbSize',W.DWORD),('hWnd',W.HWND),('uID',W.UINT),('uFlags',W.UINT),
        ('uCallbackMessage',W.UINT),('hIcon',W.HICON),('szTip',W.WCHAR*128),
        ('dwState',W.DWORD),('dwStateMask',W.DWORD),('szInfo',W.WCHAR*256),
        ('uVersion',W.UINT),('szInfoTitle',W.WCHAR*64),('dwInfoFlags',W.DWORD),
        ('guidItem',GUID),('hBalloonIcon',W.HICON)]


def icon_pixels(connected):
    """Original 32px steering-wheel mark; native BGRA and one-bit AND mask."""
    pixels=bytearray();mask=bytearray()
    for y in range(31,-1,-1):
        row=bytearray([255]*4)
        for x in range(32):
            dx,dy=x-14.5,y-14.5;r=math.hypot(dx,dy)
            wheel=9.3<=r<=12.2 or r<2.3 or (r<10 and (abs(dy)<1.2 or abs(dx-dy*.65)<1.3 and dy>0))
            badge=math.hypot(x-25,y-25)<5
            if badge:color=(71,209,158) if connected else (225,167,67)
            elif wheel:color=(91,207,220)
            else:color=None
            if color:
                red,green,blue=color;pixels.extend((blue,green,red,255));row[x//8]&=~(128>>(x%8))
            else:pixels.extend((0,0,0,0))
        mask.extend(row)
    return bytes(mask),bytes(pixels)


class TrayIcon:
    def __init__(self,events):
        self.events=events;self.ready=threading.Event();self.stopped=threading.Event()
        self.available=False;self.connected=False;self.hwnd=None;self.thread=None
        self._closing=False;self._icons=[];self._last_connected=None

    def start(self):
        if self.thread is not None:return
        if os.name!='nt':raise OSError('Icône de synchronisation disponible sur Windows uniquement.')
        self.thread=threading.Thread(target=self._run,name='DDF-350 notification icon',daemon=True)
        self.thread.start()

    def set_connected(self,value):
        value=bool(value)
        if value==self.connected:return
        self.connected=value
        if self.hwnd:self.user.PostMessageW(self.hwnd,UPDATE,0,0)

    def refresh_language(self):
        if self.hwnd:self.user.PostMessageW(self.hwnd,UPDATE,0,0)

    def close(self):
        self._closing=True
        if self.hwnd:self.user.PostMessageW(self.hwnd,WM_CLOSE,0,0)
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=2)

    def _bind(self,dll,name,args,result):
        fn=getattr(dll,name);fn.argtypes=args;fn.restype=result;return fn

    def _setup(self):
        self.user=C.WinDLL('user32',use_last_error=True)
        self.shell=C.WinDLL('shell32',use_last_error=True)
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        self.proc_type=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        proc_type=self.proc_type
        class WindowClass(C.Structure):
            _fields_=[('style',W.UINT),('lpfnWndProc',proc_type),('cbClsExtra',C.c_int),
                ('cbWndExtra',C.c_int),('hInstance',W.HINSTANCE),('hIcon',W.HICON),
                ('hCursor',W.HANDLE),('hbrBackground',W.HANDLE),('lpszMenuName',W.LPCWSTR),('lpszClassName',W.LPCWSTR)]
        self.WindowClass=WindowClass
        b=self._bind
        b(self.kernel,'GetModuleHandleW',[W.LPCWSTR],W.HINSTANCE)
        b(self.user,'RegisterClassW',[C.POINTER(WindowClass)],W.WORD)
        b(self.user,'UnregisterClassW',[W.LPCWSTR,W.HINSTANCE],W.BOOL)
        b(self.user,'CreateWindowExW',[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p],W.HWND)
        b(self.user,'DefWindowProcW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],C.c_ssize_t)
        b(self.user,'DestroyWindow',[W.HWND],W.BOOL)
        b(self.user,'IsWindow',[W.HWND],W.BOOL)
        b(self.user,'GetMessageW',[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT],C.c_int)
        b(self.user,'TranslateMessage',[C.POINTER(W.MSG)],W.BOOL)
        b(self.user,'DispatchMessageW',[C.POINTER(W.MSG)],C.c_ssize_t)
        b(self.user,'PostMessageW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],W.BOOL)
        b(self.user,'PostQuitMessage',[C.c_int],None)
        b(self.user,'RegisterWindowMessageW',[W.LPCWSTR],W.UINT)
        b(self.user,'CreateIcon',[W.HINSTANCE,C.c_int,C.c_int,C.c_ubyte,C.c_ubyte,C.c_void_p,C.c_void_p],W.HICON)
        b(self.user,'DestroyIcon',[W.HICON],W.BOOL)
        b(self.user,'CreatePopupMenu',[],W.HMENU)
        b(self.user,'AppendMenuW',[W.HMENU,W.UINT,C.c_size_t,W.LPCWSTR],W.BOOL)
        b(self.user,'DestroyMenu',[W.HMENU],W.BOOL)
        b(self.user,'GetCursorPos',[C.POINTER(W.POINT)],W.BOOL)
        b(self.user,'SetForegroundWindow',[W.HWND],W.BOOL)
        b(self.user,'TrackPopupMenu',[W.HMENU,W.UINT,C.c_int,C.c_int,C.c_int,W.HWND,C.c_void_p],W.UINT)
        b(self.shell,'Shell_NotifyIconW',[W.DWORD,C.POINTER(NOTIFYICONDATA)],W.BOOL)

    def _notify(self,action):
        data=NOTIFYICONDATA();data.cbSize=C.sizeof(data);data.hWnd=self.hwnd;data.uID=1
        data.uFlags=1|2|4;data.uCallbackMessage=CALLBACK
        data.hIcon=self._icons[int(self.connected)]
        data.szTip=tr('DDF-350 · CH1/CH2 actifs' if self.connected else 'DDF-350 · en attente de la télécommande')
        result=bool(self.shell.Shell_NotifyIconW(action,C.byref(data)))
        if action==0:self.available=result
        elif action==2:self.available=False
        return result

    def _menu(self):
        menu=self.user.CreatePopupMenu()
        if not menu:return
        try:
            self.user.AppendMenuW(menu,0,1001,tr('Ouvrir DDF-350'))
            self.user.AppendMenuW(menu,0x800,0,tr(None))
            self.user.AppendMenuW(menu,0,1002,tr('Quitter la synchronisation'))
            point=W.POINT();self.user.GetCursorPos(C.byref(point))
            self.user.SetForegroundWindow(self.hwnd)
            command=self.user.TrackPopupMenu(menu,0x100|0x80|2,point.x,point.y,0,self.hwnd,None)
            self.user.PostMessageW(self.hwnd,WM_NULL,0,0)
            if command==1001:self.events.put(('open',None))
            elif command==1002:self.events.put(('quit',None))
        finally:self.user.DestroyMenu(menu)

    def _window_proc(self,hwnd,message,wparam,lparam):
        try:
            if message==CALLBACK:
                if lparam in (WM_LBUTTONUP,WM_LBUTTONDBLCLK):self.events.put(('open',None))
                elif lparam in (WM_RBUTTONUP,WM_CONTEXTMENU):self._menu()
                return 0
            if message==UPDATE:
                if not self._notify(1):self._notify(0)
                return 0
            if message==self.taskbar_message:
                self._notify(0);self.events.put(('tray_ready',self.available));return 0
            if message==self.show_message:
                self.events.put(('radio' if wparam==1 else 'open',None));return 0
            if message==WM_CLOSE:
                self._notify(2);self.user.DestroyWindow(hwnd);return 0
            if message==WM_DESTROY:
                self.user.PostQuitMessage(0);return 0
        except Exception as error:self.events.put(('tray_error',str(error)))
        return self.user.DefWindowProcW(hwnd,message,wparam,lparam)

    def _run(self):
        registered=False
        try:
            self._setup()
            self.instance=self.kernel.GetModuleHandleW(None)
            self.class_name=f'DDF350SyncTray-{os.getpid()}'
            self.taskbar_message=self.user.RegisterWindowMessageW('TaskbarCreated')
            self.show_message=self.user.RegisterWindowMessageW('DDF350SyncShow')
            self.callback=self.proc_type(self._window_proc)
            wc=self.WindowClass();wc.lpfnWndProc=self.callback;wc.hInstance=self.instance;wc.lpszClassName=self.class_name
            if not self.user.RegisterClassW(C.byref(wc)):raise C.WinError(C.get_last_error())
            registered=True
            for connected in (False,True):
                mask,pixels=icon_pixels(connected)
                hicon=self.user.CreateIcon(self.instance,32,32,1,32,C.create_string_buffer(mask),C.create_string_buffer(pixels))
                if not hicon:raise C.WinError(C.get_last_error())
                self._icons.append(hicon)
            self.hwnd=self.user.CreateWindowExW(0x80,self.class_name,'DDF350 Sync',0,0,0,0,0,None,None,self.instance,None)
            if not self.hwnd:raise C.WinError(C.get_last_error())
            self._notify(0)
            self.ready.set();self.events.put(('tray_ready',self.available))
            if self._closing:self.user.PostMessageW(self.hwnd,WM_CLOSE,0,0)
            msg=W.MSG()
            while True:
                result=self.user.GetMessageW(C.byref(msg),None,0,0)
                if result==0:break
                if result<0:raise C.WinError(C.get_last_error())
                self.user.TranslateMessage(C.byref(msg));self.user.DispatchMessageW(C.byref(msg))
        except Exception as error:self.events.put(('tray_error',str(error)))
        finally:
            if self.hwnd:
                self._notify(2)
                if self.user.IsWindow(self.hwnd):self.user.DestroyWindow(self.hwnd)
            self.hwnd=None;self.available=False
            for icon in self._icons:self.user.DestroyIcon(icon)
            if registered:self.user.UnregisterClassW(self.class_name,self.instance)
            self.ready.set();self.stopped.set()


class SingleInstance:
    """One sync process per interactive Windows session; second launch opens it."""
    def __init__(self):self.handle=None;self.already_running=False
    def acquire(self):
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];kernel.CreateMutexW.restype=W.HANDLE
        C.set_last_error(0)
        self.handle=kernel.CreateMutexW(None,False,'Local\\DDF350ToolkitSync')
        if not self.handle:raise C.WinError(C.get_last_error())
        self.already_running=C.get_last_error()==183
        return not self.already_running
    def show_existing(self, *, radio=False):
        user=C.WinDLL('user32',use_last_error=True)
        user.RegisterWindowMessageW.argtypes=[W.LPCWSTR];user.RegisterWindowMessageW.restype=W.UINT
        user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];user.PostMessageW.restype=W.BOOL
        message=user.RegisterWindowMessageW('DDF350SyncShow')
        user.PostMessageW(W.HWND(0xffff),message,1 if radio else 0,0)
    def close(self):
        if self.handle:
            kernel=C.WinDLL('kernel32',use_last_error=True)
            kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle(self.handle);self.handle=None
