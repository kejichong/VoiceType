"""全局热键：RegisterHotKey 独立消息线程。

选择 RegisterHotKey 而非低级键盘钩子：系统级注册、不加载驱动、
不会被杀软当成键盘记录器，且无需管理员权限。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 0xB801

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

_MODS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN, "cmd": MOD_WIN,
}

_VK = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "backspace": 0x08, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _i in range(1, 25):
    _VK[f"f{_i}"] = 0x6F + _i
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _VK[_c.lower()] = ord(_c)
for _d in "0123456789":
    _VK[_d] = ord(_d)


class HotkeyError(Exception):
    pass


def parse_hotkey(binding: str) -> tuple[int, int]:
    """'Ctrl+Alt+Space' -> (modifiers, vk)。无法识别的键名抛 HotkeyError。"""
    parts = [p.strip().lower() for p in binding.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("热键为空")
    mods = 0
    key_part = ""
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        else:
            key_part = p
    if not key_part:
        raise HotkeyError("热键缺少主键，例如 Ctrl+Alt+Space")
    if key_part not in _VK:
        raise HotkeyError(f"不支持的按键：{key_part}")
    if mods == 0:
        raise HotkeyError("必须包含至少一个修饰键（Ctrl / Alt / Shift / Win）")
    return mods, _VK[key_part]


class HotkeyManager:
    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._tid: int = 0
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: str | None = None
        self._mods = 0
        self._vk = 0

    def start(self, binding: str) -> None:
        mods, vk = parse_hotkey(binding)
        self._mods, self._vk = mods, vk
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        if self._error:
            raise HotkeyError(self._error)

    def _run(self) -> None:
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        # MOD_NOREPEAT：长按不重复触发，避免按住键连开好几个会话
        if not user32.RegisterHotKey(None, HOTKEY_ID, self._mods | MOD_NOREPEAT, self._vk):
            code = ctypes.get_last_error()
            self._error = (
                f"热键注册失败（错误码 {code}），"
                "该组合可能已被微信、输入法或其他软件占用，请换一个"
            )
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while not self._stop.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    try:
                        self._callback()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self) -> None:
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
