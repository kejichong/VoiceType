"""开机自启：写 HKCU 的 Run 项。

用当前用户注册表（HKCU），不需要管理员权限，也不改系统级设置。
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "VoiceType"


def _command() -> str:
    """返回要写进注册表的启动命令。

    打包后（PyInstaller）sys.executable 就是 exe 本身；
    开发态则用 pythonw 跑 run.py，且不加 /console 黑框。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    launcher = pyw if pyw.exists() else exe
    run_py = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{launcher}" "{run_py}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    """开启/关闭开机自启。失败抛 OSError，由调用方决定怎么提示。"""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def sync_with_config(desired: bool) -> str:
    """让注册表与配置一致，返回一句可展示的状态说明。"""
    try:
        if desired:
            set_enabled(True)
            return "已设置为开机自动启动"
        set_enabled(False)
        return "已取消开机自动启动"
    except OSError as exc:
        return f"开机自启设置失败：{exc}"
