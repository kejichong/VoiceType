"""对打包后的 exe 做真实双击复现：连开两次，验证窗口可见与唤醒。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
EXE = PROJ / "dist" / "VoiceType" / "VoiceType.exe"
LOG = Path(os.environ["APPDATA"]) / "VoiceType" / "logs" / "app.log"

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    lines.append(msg)


def our_windows() -> list[str]:
    out: list[str] = []

    def cb(hwnd, _lp):
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c, 256)
        if not c.value.startswith("Qt6120"):
            return True
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, t, 512)
        out.append(f"pid={p.value} vis={bool(user32.IsWindowVisible(hwnd))} "
                   f"cls={c.value} title={t.value!r}")
        return True

    user32.EnumWindows(PROC(cb), 0)
    return out


def read_log() -> str:
    if not LOG.exists():
        return ""
    with open(LOG, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def kill_all() -> None:
    subprocess.run(["taskkill", "/IM", "VoiceType.exe", "/F"],
                   capture_output=True)
    time.sleep(1.2)


def main() -> int:
    if not EXE.exists():
        log(f"EXE missing: {EXE}")
        return 2

    kill_all()
    if LOG.exists():
        try:
            LOG.unlink()
        except OSError:
            pass

    log("--- 第一次双击（启动）---")
    a = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    time.sleep(7)
    log(f"A alive = {a.poll() is None}")
    wins = our_windows()
    log(f"窗口 {len(wins)} 个:")
    for w in wins:
        log("  " + w)
    has_dialog = any("vis=True" in w and "设置" in w for w in wins)

    log("--- 第二次双击（应唤醒，不新起进程）---")
    b = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    time.sleep(4)
    log(f"B 已退出 = {b.poll() is not None} (exit={b.poll()})")

    txt = read_log()
    log("--- 日志 ---")
    for line in txt.splitlines():
        log("  " + line)

    woke = "收到重复启动信号" in txt
    log(f"RESULT: dialog_visible={'OK' if has_dialog else 'FAIL'} "
        f"wake={'OK' if woke else 'FAIL'}")

    kill_all()
    (PROJ / ".venv" / "exe_wake.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if (has_dialog and woke) else 1


if __name__ == "__main__":
    sys.exit(main())
