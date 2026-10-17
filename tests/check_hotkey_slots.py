"""探测这台机器上哪些热键组合还是空的。

猜"哪个键没被占用"没有意义——显卡驱动、输入法、微信、截图工具都在默默注册
全局热键。RegisterHotKey 成功就是空的，失败就是被占了，这个结果才是真的。
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.hotkey import MOD_NOREPEAT, HOTKEY_ID, parse_hotkey  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

WM_QUIT = 0x0012

CANDIDATES = [
    "Alt+`", "Ctrl+`", "Alt+;", "Ctrl+;", "Alt+'", "Alt+.", "Alt+,",
    "Ctrl+Alt+Space", "Shift+Alt+Space", "Ctrl+Shift+Space",
    "Alt+F12", "Ctrl+F12", "Alt+Insert", "Alt+Pause",
]


def try_register(binding: str) -> tuple[bool, str]:
    """在一个独立消息线程里试注册，成功即释放。"""
    try:
        mods, vk = parse_hotkey(binding)
    except Exception as exc:
        return False, f"无法解析：{exc}"

    result: dict[str, object] = {}
    ready = threading.Event()
    tid_box: list[int] = []
    stop = threading.Event()

    def run() -> None:
        tid_box.append(ctypes.windll.kernel32.GetCurrentThreadId())
        ok = user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk)
        result["code"] = ctypes.get_last_error() if not ok else 0
        result["ok"] = bool(ok)
        ready.set()
        msg = wintypes.MSG()
        while not stop.is_set():
            if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) in (0, -1):
                break
        user32.UnregisterHotKey(None, HOTKEY_ID)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(2.0)
    time.sleep(0.05)
    stop.set()
    if tid_box:
        user32.PostThreadMessageW(tid_box[0], WM_QUIT, 0, 0)
    t.join(timeout=1.0)
    ok = bool(result.get("ok"))
    return ok, ("" if ok else f"错误码 {result.get('code')}")


def main() -> int:
    free: list[str] = []
    print(f"{'组合':<20} {'结果':<8} 说明")
    print("-" * 60)
    for b in CANDIDATES:
        ok, err = try_register(b)
        mark = "可用" if ok else "被占用"
        if ok:
            free.append(b)
        print(f"{b:<20} {mark:<8} {err}")
        time.sleep(0.05)

    print("\n可用组合：" + ("、".join(free) if free else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
