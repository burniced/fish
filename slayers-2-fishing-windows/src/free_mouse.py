from __future__ import annotations

import mmap
import os
import struct
import subprocess
import sys
import threading
import time

IS_WINDOWS = sys.platform == "win32"

_LAYOUT = struct.Struct("<iii")
_shared: mmap.mmap | None = None

_POLL_SEC = 0.002
_TIMER_MS = 500
_REHOOK_TICKS = 60
_FRONT_RECHECK_SEC = 1.0


def note_macro_cursor(x: int, y: int) -> None:
    shm = _shared
    if shm is None:
        return
    try:
        seq = struct.unpack_from("<i", shm, 0)[0]
        struct.pack_into("<ii", shm, 4, int(x), int(y))
        struct.pack_into("<i", shm, 0, (seq + 1) & 0x7FFFFFFF)
    except (ValueError, OSError, struct.error):
        pass


class FreeMouse:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        global _shared
        if not IS_WINDOWS:
            return False
        if self.running:
            return True
        tag = "S2FreeMouse%d" % os.getpid()
        try:
            if _shared is None:
                _shared = mmap.mmap(-1, _LAYOUT.size, tagname=tag)
            self._proc = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), str(os.getpid()), tag],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self._proc = None
            return False
        return True

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def _serve(parent_pid: int, tag: str) -> int:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except (AttributeError, OSError):
        pass

    LRESULT = ctypes.c_ssize_t
    WH_MOUSE_LL = 14
    HC_ACTION = 0
    WM_MOUSEMOVE = 0x0200
    WM_TIMER = 0x0113
    LLMHF_INJECTED = 0x01
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = (
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        )

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetClassNameW.argtypes = (ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.argtypes = (ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int)
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.GetClipCursor.argtypes = (ctypes.POINTER(wintypes.RECT),)
    user32.ClipCursor.argtypes = (ctypes.c_void_p,)
    user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
    user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
    user32.SetTimer.restype = ctypes.c_size_t
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    parent = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
    if not parent:
        return 1
    try:
        shm = mmap.mmap(-1, _LAYOUT.size, tagname=tag)
    except OSError:
        return 1

    lock = threading.Lock()
    pos = [0, 0]
    front = {"hwnd": None, "roblox": False, "at": 0.0}

    def get_cursor() -> tuple[int, int]:
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return int(p.x), int(p.y)

    def roblox_in_front() -> bool:
        hwnd = user32.GetForegroundWindow()
        now = time.monotonic()
        if hwnd != front["hwnd"] or now > front["at"] + _FRONT_RECHECK_SEC:
            is_roblox = False
            if hwnd:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                is_roblox = buf.value.lower() == "windowsclient"
                if not is_roblox:
                    user32.GetWindowTextW(hwnd, buf, 256)
                    is_roblox = buf.value.strip().lower() == "roblox"
            front.update(hwnd=hwnd, roblox=is_roblox, at=now)
        return bool(front["roblox"])

    def place(x: int, y: int) -> None:
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        right = left + user32.GetSystemMetrics(78) - 1
        bottom = top + user32.GetSystemMetrics(79) - 1
        x = min(max(int(x), left), right)
        y = min(max(int(y), top), bottom)
        clip = wintypes.RECT()
        if user32.GetClipCursor(ctypes.byref(clip)) and (
            clip.left > left or clip.top > top or clip.right <= right or clip.bottom <= bottom
        ):
            user32.ClipCursor(None)
        user32.SetCursorPos(x, y)
        pos[0], pos[1] = get_cursor()

    def hook_proc(code, wparam, lparam):
        try:
            if code == HC_ACTION and wparam == WM_MOUSEMOVE:
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                with lock:
                    if not (info.flags & LLMHF_INJECTED) and roblox_in_front():
                        cx, cy = get_cursor()
                        place(pos[0] + info.pt.x - cx, pos[1] + info.pt.y - cy)
                        return 1
                    pos[0], pos[1] = int(info.pt.x), int(info.pt.y)
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    callback = HOOKPROC(hook_proc)
    module = kernel32.GetModuleHandleW(None)

    def install():
        return user32.SetWindowsHookExW(WH_MOUSE_LL, callback, module, 0)

    with lock:
        pos[0], pos[1] = get_cursor()
    hook = install()
    if not hook:
        return 1

    def keep_cursor() -> None:
        last_seq = struct.unpack_from("<i", shm, 0)[0]
        while True:
            try:
                with lock:
                    seq = struct.unpack_from("<i", shm, 0)[0]
                    if seq != last_seq:
                        last_seq = seq
                        pos[0], pos[1] = struct.unpack_from("<ii", shm, 4)
                    else:
                        cur = get_cursor()
                        if not roblox_in_front():
                            pos[0], pos[1] = cur
                        elif cur != (pos[0], pos[1]):
                            place(pos[0], pos[1])
            except Exception:
                pass
            time.sleep(_POLL_SEC)

    threading.Thread(target=keep_cursor, daemon=True).start()

    user32.SetTimer(None, 0, _TIMER_MS, None)
    msg = wintypes.MSG()
    ticks = 0
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_TIMER:
            if kernel32.WaitForSingleObject(parent, 0) == WAIT_OBJECT_0:
                break
            ticks += 1
            if ticks % _REHOOK_TICKS == 0:
                fresh = install()
                if fresh:
                    user32.UnhookWindowsHookEx(hook)
                    hook = fresh
            continue
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    user32.UnhookWindowsHookEx(hook)
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and IS_WINDOWS:
        os._exit(_serve(int(sys.argv[1]), sys.argv[2]))
