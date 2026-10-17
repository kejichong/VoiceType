"""验证桌面快捷方式真的能用 —— 模拟一次"双击"。

自己把 .lnk 解析出来不算数（那是我的解析器说的），必须让 Windows 自己打开它：
用 ShellExecuteW 走 Shell 的解析路径，和用户在资源管理器里双击是同一条路。
启动成功后再确认进程确实起来了，最后收掉（这是测试起的，不是用户要留着的）。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

LNK = Path(r"C:\Users\10129\Desktop\语音输入.lnk")
TARGET = Path(r"D:\Tools\VoiceType\VoiceType.exe")
LOG = Path.home() / "AppData" / "Roaming" / "VoiceType" / "logs" / "app.log"

SEE_MASK_NOCLOSEPROCESS = 0x0000_0040
SEE_MASK_ASYNCOK = 0x0010_0000        # 不等 DDE 会话完成，否则 ShellExecute 可能长时间不返回


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND), ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p), ("hKeyClass", ctypes.c_void_p),
        ("dwHotKey", wintypes.DWORD), ("hIcon", ctypes.c_void_p),
        ("hProcess", wintypes.HANDLE),
    ]


shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
shell32.ShellExecuteExW.restype = wintypes.BOOL
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def log_has(text: str, offset: int) -> bool:
    try:
        with open(LOG, "rb") as f:      # 进程占用，必须共享读
            f.seek(offset)
            return text in f.read().decode("utf-8", errors="replace")
    except OSError:
        return False


def main() -> int:
    ok_all = True

    def check(ok: bool, label: str) -> None:
        nonlocal ok_all
        ok_all &= ok
        print(("PASS " if ok else "FAIL ") + label)

    check(LNK.exists(), f"桌面快捷方式存在：{LNK}")
    check(TARGET.exists(), f"它指向的程序存在：{TARGET}")
    check(
        (TARGET.parent / "_internal").is_dir(),
        "目标 exe 旁边有 _internal（依赖齐全，不是个孤儿）",
    )
    if not ok_all:
        return 1

    subprocess.run(["taskkill", "/F", "/IM", "VoiceType.exe"], capture_output=True)
    time.sleep(0.7)

    offset = LOG.stat().st_size if LOG.exists() else 0
    # ShellExecuteEx 走的就是"双击"那条路：Shell 自己读 .lnk、解析目标、拉起进程。
    # 必须带 SEE_MASK_ASYNCOK —— 否则 Shell 会等 DDE 会话完成，调用几十秒不返回。
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_ASYNCOK
    info.lpVerb = "open"
    info.lpFile = str(LNK)
    info.nShow = 1
    ok_exec = bool(shell32.ShellExecuteExW(ctypes.byref(info)))
    check(ok_exec, "ShellExecuteEx 成功打开快捷方式（和资源管理器双击同一条路）")
    if not ok_exec:
        print(f"  错误码 {ctypes.get_last_error()}")
        return 1
    hproc = info.hProcess

    end = time.monotonic() + 25
    ready = False
    while time.monotonic() < end:
        if log_has("启动完成", offset):
            ready = True
            break
        time.sleep(0.2)
    check(ready, "程序确实起来了（日志出现「启动完成」）")

    # 别指望 hProcess：走 Shell 这条路径时它经常是 NULL（返回码仍是成功），
    # 但程序照样起来了。判活要用进程列表。
    ps = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq VoiceType.exe", "/NH"],
        capture_output=True,
    )
    alive = "VoiceType.exe" in ps.stdout.decode("utf-8", errors="replace")
    check(alive, "进程列表里能看到 VoiceType.exe")

    print("\n本次启动的日志：")
    try:
        with open(LOG, "rb") as f:
            f.seek(offset)
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        tail = ""
    for line in tail.strip().splitlines()[:5]:
        print("  " + line)

    # 这是测试拉起来的，用完就收，别在后台留一个抢热键的实例
    if hproc:
        _kernel32.TerminateProcess(hproc, 0)
        _kernel32.CloseHandle(hproc)
    subprocess.run(["taskkill", "/F", "/IM", "VoiceType.exe"], capture_output=True)
    time.sleep(0.5)

    print("\n" + ("全部通过 —— 桌面这个图标可以直接双击" if ok_all else "存在失败项"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
