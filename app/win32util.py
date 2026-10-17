"""Win32 底层能力封装：DPI、窗口焦点、剪贴板、键盘注入。

全部用 ctypes 实现（零第三方依赖），便于打包。
注意：所有返回句柄/指针的 API 必须显式声明 restype，
否则 64 位下会被截断成 32 位 int 导致崩溃。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------- 常量 ----------------
CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_SYLK = 4
CF_DIF = 5
CF_TIFF = 6
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_PENDATA = 10
CF_RIFF = 11
CF_WAVE = 12
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_LOCALE = 16
CF_OWNERDISPLAY = 0x0080
CF_DSPTEXT = 0x0081
CF_DSPBITMAP = 0x0082
CF_DSPMETAFILEPICT = 0x0083
CF_DSPENHMETAFILE = 0x008E

GMEM_MOVEABLE = 0x0002
SW_RESTORE = 9

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56

# GDI 句柄类 / 私有格式：不是 HGLOBAL，不能按内存块备份
_NON_HGLOBAL = {
    CF_BITMAP, CF_PALETTE, CF_METAFILEPICT, CF_ENHMETAFILE,
    CF_OWNERDISPLAY, CF_DSPTEXT, CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE,
}

# ---------------- 函数签名 ----------------
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL

user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT

user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE

user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


# ---------------- DPI ----------------
def enable_dpi_awareness() -> None:
    """声明 DPI 感知。必须在创建任何窗口之前调用，否则高缩放下坐标算错。"""
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# ---------------- 窗口焦点 ----------------
def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def set_foreground_window(hwnd: int) -> bool:
    """把焦点还回目标窗口。

    Windows 限制只有前台进程能抢焦点，所以用 AttachThreadInput
    把当前线程输入队列挂到目标窗口线程上，绕过这个限制。
    """
    if not is_window(hwnd):
        return False
    if get_foreground_window() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    fg = get_foreground_window()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    cur_tid = kernel32.GetCurrentThreadId()
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        ok = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)

    if not ok:
        # 兜底：模拟一次 ALT 键，解除系统的前台锁定
        _send_alt_tap()
        time.sleep(0.02)
        ok = bool(user32.SetForegroundWindow(hwnd))
    return ok


def _send_alt_tap() -> None:
    alt = 0x12
    _send_vk(alt, up=False)
    _send_vk(alt, up=True)


# ---------------- 键盘注入 ----------------
def _make_input(wvk: int, up: bool, unicode_scan: int | None = None) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    flags = 0
    scan = 0
    if unicode_scan is not None:
        flags |= KEYEVENTF_UNICODE
        scan = unicode_scan
    if up:
        flags |= KEYEVENTF_KEYUP
    inp.u.ki.wVk = 0 if unicode_scan is not None else wvk
    inp.u.ki.wScan = scan
    inp.u.ki.dwFlags = flags
    inp.u.ki.time = 0
    inp.u.ki.dwExtraInfo = None
    return inp


def _send_vk(vk: int, up: bool) -> None:
    inp = _make_input(vk, up)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_unicode_text(text: str) -> None:
    """逐字符 Unicode 注入。不碰剪贴板，但部分应用（Electron/终端）会失效。"""
    inputs = []
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:  # 代理对
            code -= 0x10000
            hi = 0xD800 + (code >> 10)
            lo = 0xDC00 + (code & 0x3FF)
            inputs.append(_make_input(0, False, hi))
            inputs.append(_make_input(0, True, hi))
            inputs.append(_make_input(0, False, lo))
            inputs.append(_make_input(0, True, lo))
        else:
            inputs.append(_make_input(0, False, code))
            inputs.append(_make_input(0, True, code))
    if not inputs:
        return
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def send_ctrl_v() -> None:
    """模拟 Ctrl+V。"""
    _send_vk(VK_CONTROL, up=False)
    time.sleep(0.01)
    _send_vk(VK_V, up=False)
    time.sleep(0.01)
    _send_vk(VK_V, up=True)
    time.sleep(0.01)
    _send_vk(VK_CONTROL, up=True)


# ---------------- 剪贴板 ----------------
def _open_clipboard(retries: int = 10, delay: float = 0.02) -> bool:
    """剪贴板是全局独占资源，可能被别的程序占用，需要重试。"""
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def set_clipboard_text(text: str) -> bool:
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = kernel32.GlobalLock(h)
        if not p:
            kernel32.GlobalFree(h)
            return False
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True
    finally:
        user32.CloseClipboard()


def get_clipboard_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def register_clipboard_format(name: str) -> int:
    return int(user32.RegisterClipboardFormatW(name))


class ClipboardSnapshot:
    """剪贴板全格式快照。

    备份所有 HGLOBAL 类格式（纯文本、DIB 位图、文件列表、HTML、RTF 等），
    恢复时原样写回。GDI 句柄类格式（CF_BITMAP / CF_PALETTE 等）无法按内存
    备份，跳过；但绝大多数程序存图时同时会写 CF_DIB，所以粘贴图片仍可还原。
    """

    def __init__(self) -> None:
        self.entries: list[tuple[int, bytes]] = []
        self.skipped: list[int] = []
        self.valid = False

    @classmethod
    def capture(cls) -> "ClipboardSnapshot":
        snap = cls()
        if not _open_clipboard():
            return snap
        try:
            fmt = 0
            while True:
                fmt = user32.EnumClipboardFormats(fmt)
                if fmt == 0:
                    break
                if fmt in _NON_HGLOBAL:
                    snap.skipped.append(fmt)
                    continue
                h = user32.GetClipboardData(fmt)
                if not h:
                    # 延迟渲染格式：数据尚未实体化，跳过
                    snap.skipped.append(fmt)
                    continue
                size = kernel32.GlobalSize(h)
                if not size:
                    snap.skipped.append(fmt)
                    continue
                p = kernel32.GlobalLock(h)
                if not p:
                    snap.skipped.append(fmt)
                    continue
                try:
                    snap.entries.append((fmt, ctypes.string_at(p, size)))
                finally:
                    kernel32.GlobalUnlock(h)
            snap.valid = True
        finally:
            user32.CloseClipboard()
        return snap

    def restore(self) -> bool:
        """把快照写回剪贴板。失败的格式静默跳过，不影响其余内容。"""
        if not self.valid:
            return False
        if not _open_clipboard():
            return False
        try:
            user32.EmptyClipboard()
            for fmt, data in self.entries:
                h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not h:
                    continue
                p = kernel32.GlobalLock(h)
                if not p:
                    kernel32.GlobalFree(h)
                    continue
                ctypes.memmove(p, data, len(data))
                kernel32.GlobalUnlock(h)
                if not user32.SetClipboardData(fmt, h):
                    kernel32.GlobalFree(h)
            return True
        finally:
            user32.CloseClipboard()

    def summary(self) -> str:
        names = {CF_TEXT: "TEXT", CF_UNICODETEXT: "UNICODETEXT", CF_DIB: "DIB",
                 CF_HDROP: "HDROP(文件)", CF_OEMTEXT: "OEMTEXT", CF_LOCALE: "LOCALE",
                 CF_WAVE: "WAVE", CF_RIFF: "RIFF"}
        parts = []
        for fmt, data in self.entries:
            label = names.get(fmt, f"fmt#{fmt}")
            parts.append(f"{label}({len(data)}B)")
        return ", ".join(parts) if parts else "(空)"
