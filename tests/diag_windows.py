"""一次性诊断：列出所有顶层窗口，找悬浮球到底叫什么、在不在。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]

rows = []


@WNDENUMPROC
def cb(hwnd, _lparam):
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetWindowTextW(hwnd, buf, 256)
    title = buf.value if n else ""
    cbuf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cbuf, 256)
    vis = bool(user32.IsWindowVisible(hwnd))
    if title or vis:
        rows.append((int(hwnd), vis, cbuf.value, title[:60]))
    return True


user32.EnumWindows(cb, 0)
print(f"共枚举到 {len(rows)} 个窗口（有标题或可见）")
for hwnd, vis, cls, title in rows:
    mark = "  " if title or "Qt" in cls else ""
    if not title and "Qt" not in cls and not vis:
        continue
    print(f"{hwnd:#x} vis={int(vis)} cls={cls:<24} title={title!r}")

hits = [r for r in rows if "悬浮" in r[3] or "语音" in r[3]]
print("\n命中：")
for h in hits:
    print(f"  {h[0]:#x} vis={int(h[1])} cls={h[2]} title={h[3]!r}") if hits else print("  无")
