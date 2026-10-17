"""诊断"点球没反应"：到底是产品回归，还是测试把坐标算错了。

GetWindowRect 给的坐标和 SetCursorPos 要的坐标可能不是同一套 —— 屏幕 150% 缩放时
存在逻辑像素与物理像素两套坐标系。判断方法很简单：用 WindowFromPoint 问 Windows
"这个坐标上盖着哪个窗口"，答案是不是球，一眼就知道。
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
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]


class POINT(ctypes.Structure):
    """WindowFromPoint 收的是一个 POINT 结构，不是两个整数参数。

    64 位下 ctypes 传两个 c_long 会占两个寄存器，而 POINT 是 8 字节只占一个 ——
    参数错位，返回值不可信。
    """
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.WindowFromPoint.argtypes = [POINT]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]


def find_ball() -> int:
    found: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        if user32.GetWindowTextW(hwnd, buf, 256) and buf.value.startswith(BALL_TITLE):
            found.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


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
    w, h = r.right - r.left, r.bottom - r.top
    cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    print(f"球 hwnd={hwnd:#x}")
    print(f"GetWindowRect = ({r.left},{r.top})-({r.right},{r.bottom})  尺寸 {w}x{h}")
    print(f"矩形中心 = ({cx}, {cy})")

    under = int(user32.WindowFromPoint(POINT(cx, cy)) or 0)
    print(f"\nWindowFromPoint(矩形中心) = {under:#x}  "
          f"{'← 就是球，坐标没问题' if under == hwnd else '← 不是球！坐标系不一致'}")

    # 逐倍数试，看看到底哪套坐标能命中
    print("\n按不同倍率换算后试探：")
    for name, k in (("1.0（原样）", 1.0), ("1.5（设备像素比）", 1.5), ("0.667", 1 / 1.5)):
        tx, ty = int(cx * k), int(cy * k)
        u = int(user32.WindowFromPoint(POINT(tx, ty)) or 0)
        hit = u == hwnd
        print(f"  ×{name:<14} ({tx}, {ty}) -> {u:#x}  {'命中球' if hit else ''}")

    # 反过来：以球 hwnd 为锚，扫一圈找它真正的可点区域
    print("\n以矩形中心为原点扫描 ±60 像素，找出真正命中球的坐标：")
    hits = []
    for dy in range(-60, 61, 10):
        row = []
        for dx in range(-60, 61, 10):
            u = int(user32.WindowFromPoint(POINT(cx + dx, cy + dy)) or 0)
            row.append("#" if u == hwnd else ".")
            if u == hwnd:
                hits.append((cx + dx, cy + dy))
        print("    " + "".join(row))
    if hits:
        xs = [p[0] for p in hits]
        ys = [p[1] for p in hits]
        print(f"  命中区域 x[{min(xs)}..{max(xs)}] y[{min(ys)}..{max(ys)}]"
              f"（矩形是 x[{r.left}..{r.right}] y[{r.top}..{r.bottom}]）")
    else:
        print("  这个范围内完全点不到球")

    proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
