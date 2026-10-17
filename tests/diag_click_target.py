"""点球没反应时，先回答一个问题：点击到底落到哪个窗口上了。

思路：点击前后各枚举一次所有可见顶层窗口，比对前台窗口是谁、标题是什么。
再配合点击前后的日志差，就能分清是"点偏了"、"被别的窗口挡住"，
还是"点中了但程序自己走了别的分支（比如弹了引导窗）"。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
EXE = ROOT / "dist" / "VoiceType" / "VoiceType.exe"
LOG = Path.home() / "AppData" / "Roaming" / "VoiceType" / "logs" / "app.log"
BALL_TITLE = "语音输入 · 悬浮球"

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]


class POINT(ctypes.Structure):
    """WindowFromPoint 收的是这个结构（8 字节），不是两个整数参数。"""
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]


def all_windows() -> dict[int, str]:
    out: dict[int, str] = {}

    @WNDENUMPROC
    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(200)
            user32.GetWindowTextW(hwnd, buf, 200)
            if buf.value:
                out[int(hwnd)] = buf.value
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_ball() -> int:
    for hwnd, title in all_windows().items():
        if title.startswith(BALL_TITLE):
            return hwnd
    return 0


def main() -> int:
    subprocess.run(["taskkill", "/F", "/IM", "VoiceType.exe"], capture_output=True)
    time.sleep(0.7)
    off = LOG.stat().st_size if LOG.exists() else 0
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))

    end = time.monotonic() + 25
    while time.monotonic() < end:
        try:
            if "启动完成" in LOG.read_bytes()[off:].decode("utf-8", "replace"):
                break
        except OSError:
            pass
        time.sleep(0.2)
    print("exe 已就绪\n")

    hwnd = 0
    end = time.monotonic() + 8
    while time.monotonic() < end:
        hwnd = find_ball()
        if hwnd:
            break
        time.sleep(0.2)
    if not hwnd:
        print("没找到球")
        proc.kill()
        return 1

    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    print(f"球 {hwnd:#x}  矩形 x[{r.left}..{r.right}] y[{r.top}..{r.bottom}]  中心 ({cx},{cy})")

    user32.SetCursorPos(cx, cy)
    time.sleep(0.2)
    cur = POINT()
    user32.GetCursorPos(ctypes.byref(cur))
    under = int(user32.WindowFromPoint(POINT(cur.x, cur.y)) or 0)
    print(f"移动后光标实际在 ({cur.x},{cur.y})，该点上的窗口 = {under:#x} "
          f"{'(球)' if under == hwnd else '(不是球!)'}")

    before = all_windows()
    fg_before = int(user32.GetForegroundWindow() or 0)
    print(f"\n点击前前台 = {fg_before:#x}  {before.get(fg_before, '?')!r}")

    mark = LOG.stat().st_size
    user32.mouse_event(0x0002, 0, 0, 0, None)      # LEFT_DOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, None)      # LEFT_UP
    time.sleep(1.2)

    after = all_windows()
    fg_after = int(user32.GetForegroundWindow() or 0)
    print(f"点击后前台 = {fg_after:#x}  {after.get(fg_after, '?')!r}")

    new = {h: t for h, t in after.items() if h not in before}
    if new:
        print("\n点击后新出现的窗口：")
        for h, t in new.items():
            print(f"  {h:#x}  {t!r}")

    try:
        delta = LOG.read_bytes()[mark:].decode("utf-8", "replace")
    except OSError:
        delta = ""
    print("\n点击后的新增日志：")
    print("  " + (delta.strip().replace("\n", "\n  ") if delta.strip() else "（空 —— 什么都没发生）"))

    proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
