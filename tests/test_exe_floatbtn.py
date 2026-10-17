"""对打包后的 exe 验证悬浮球：它在不在、点它会不会抢焦点、点了能不能开始录音。

源码里测过还不够——打包后 Qt 的平台插件、窗口标志翻译都可能有出入。
所以这里对成品 exe 做三件事：
  1. 按窗口标题找到悬浮球，确认它真的可见、且带 WS_EX_NOACTIVATE（不抢焦点那个标志）
  2. 用原生鼠标事件真点一下，确认前台窗口没变、日志里出现"开始录音"
  3. 再点一下收工
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

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
LEFT_DOWN, LEFT_UP = 0x0002, 0x0004

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]


class POINT(ctypes.Structure):
    """WindowFromPoint 收的是这个结构（8 字节），不是两个整数。"""
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL


def find_ball() -> int:
    found: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        # 只能用前缀匹配：Qt 会自动把 QApplication.applicationDisplayName()
        # 追加到窗口标题后面，实际标题是「语音输入 · 悬浮球 - 语音输入」。
        # 按全等匹配会永远找不到，然后误判成"悬浮球没创建出来"。
        if user32.GetWindowTextW(hwnd, buf, 256) and buf.value.startswith(BALL_TITLE):
            found.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


def fresh_log(offset: int) -> str:
    try:
        with open(LOG, "rb") as f:      # 进程占用，必须共享读
            f.seek(offset)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def wait_ready(offset: int, timeout: float = 25.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if "启动完成" in fresh_log(offset):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    if not EXE.exists():
        print("exe 不存在，先跑 build.ps1")
        return 1

    subprocess.run(["taskkill", "/F", "/IM", "VoiceType.exe"], capture_output=True)
    time.sleep(0.7)

    offset = LOG.stat().st_size if LOG.exists() else 0
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    if not wait_ready(offset):
        print("启动超时")
        proc.kill()
        return 1
    print("程序已就绪")

    hwnd = 0
    end = time.monotonic() + 8
    while time.monotonic() < end:
        hwnd = find_ball()
        if hwnd:
            break
        time.sleep(0.2)

    ok_found = bool(hwnd)
    print(("PASS " if ok_found else "FAIL ") + f"找到悬浮球窗口（{hwnd:#x}）")
    if not ok_found:
        proc.kill()
        return 1

    ok_visible = bool(user32.IsWindowVisible(hwnd))
    print(("PASS " if ok_visible else "FAIL ") + "悬浮球处于可见状态")

    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ok_noactivate = bool(style & WS_EX_NOACTIVATE)
    ok_topmost = bool(style & WS_EX_TOPMOST)
    print(f"窗口扩展样式 = {style:#010x}")
    print(("PASS " if ok_noactivate else "FAIL ") + "带 WS_EX_NOACTIVATE（点了不抢焦点）")
    print(("PASS " if ok_topmost else "FAIL ") + "带 WS_EX_TOPMOST（悬浮在最上层）")

    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    print(f"位置 ({r.left}, {r.top})-({r.right}, {r.bottom})，中心 ({cx}, {cy})")

    # 动手之前先确认"这个坐标上盖着的确实是球"。
    # Windows 通知中心（ShellExperienceHost 的「新通知」CoreWindow）常驻 topmost，
    # 会盖住屏幕右下角一大片；它在的时候点击会被它整个吃掉，表现为"点了没反应"，
    # 极容易被误判成产品回归。所以先探，探不到就等它走。
    blocker = 0
    for _ in range(20):
        user32.SetCursorPos(cx, cy)
        time.sleep(0.15)
        under = int(user32.WindowFromPoint(POINT(cx, cy)) or 0)
        if under == hwnd:
            break
        blocker = under
        time.sleep(0.5)
    else:
        print(f"\nFAIL 球被别的窗口挡住了（{blocker:#x}），这个坐标点不到它")
        print("     常见于 Windows 通知中心浮层，属环境干扰，不是产品问题")
        proc.kill()
        return 1

    fg_before = int(user32.GetForegroundWindow() or 0)
    offset_before_click = LOG.stat().st_size
    user32.mouse_event(LEFT_DOWN, 0, 0, 0, None)
    time.sleep(0.04)
    user32.mouse_event(LEFT_UP, 0, 0, 0, None)
    time.sleep(0.8)
    fg_after = int(user32.GetForegroundWindow() or 0)
    print(f"\n点击后前台窗口：{fg_before:#x} -> {fg_after:#x}（悬浮球 {hwnd:#x}）")
    ok_focus = fg_after == fg_before
    print(("PASS " if ok_focus else "FAIL ") + "点击没有抢走前台窗口")

    new_log = fresh_log(offset_before_click)
    ok_started = "开始录音" in new_log
    print(("PASS " if ok_started else "FAIL ") + "日志里出现了「开始录音」——点球确实触发了录音")

    time.sleep(0.6)
    user32.mouse_event(LEFT_DOWN, 0, 0, 0, None)
    time.sleep(0.04)
    user32.mouse_event(LEFT_UP, 0, 0, 0, None)
    time.sleep(1.2)
    tail = fresh_log(offset_before_click)
    print("\n本次会话日志：")
    for line in tail.strip().splitlines()[-6:]:
        print("  " + line)

    proc.kill()
    ok = ok_found and ok_visible and ok_noactivate and ok_topmost and ok_focus and ok_started
    print("\n" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
