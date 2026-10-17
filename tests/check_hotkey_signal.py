"""验证热键 -> 主线程这一跳改走 Qt 信号后依然有效。

热键回调运行在 RegisterHotKey 的消息线程上，不能直接碰 Qt 控件，
所以必须跨线程投递。原先是扔进队列等 50ms 轮询，现在改成 emit 信号，
这条路径一旦接错就是"按了没反应"，必须在源码态先证明它通。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".venv" / "testhome"
HOME.mkdir(parents=True, exist_ok=True)
os.environ["VOICETYPE_HOME"] = str(HOME)
sys.path.insert(0, str(ROOT))

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]


def tap() -> None:
    """按下配置里那个测试专用组合键 Ctrl+Alt+Shift+F11。"""
    for vk in (0x11, 0x12, 0x10, 0x7A):      # Ctrl, Alt, Shift, F11
        user32.keybd_event(vk, 0, 0, None)
    for vk in (0x7A, 0x10, 0x12, 0x11):
        user32.keybd_event(vk, 0, 0x0002, None)


def pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.003)


def main() -> int:
    # 必须用测试专用的组合键：Ctrl+Alt+Space 是产品默认键，
    # 用户机器上只要 VoiceType 正在跑就已经被它注册了，抢不到（错误码 1409），
    # 那不是代码问题，是测试自己撞上了生产实例。
    (HOME / "config.json").write_text(json.dumps({
        "engine": {"type": "mock"},
        "hotkey": {"binding": "Ctrl+Alt+Shift+F11"},
    }, ensure_ascii=False), encoding="utf-8")

    from PySide6.QtWidgets import QApplication

    from app.config import Config
    from app.main import Controller
    from app.state import State

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    ctl = Controller(Config.load())
    ctl.start()
    pump(app, 400)

    if ctl.hotkey is None:
        print("FAIL 热键注册失败，无法测试")
        return 1
    print(f"热键已注册：{ctl.sm.state.value}")

    t0 = time.monotonic()
    tap()
    while time.monotonic() - t0 < 2.0:
        if ctl.sm.state == State.RECORDING:
            break
        pump(app, 5)
    reached = (time.monotonic() - t0) * 1000
    ok = ctl.sm.state == State.RECORDING
    print(("PASS " if ok else "FAIL ") + f"按键 -> 进入录音状态 {reached:.0f}ms")

    if ok:
        pump(app, 600)
        tap()
        pump(app, 1500)
        ok2 = ctl.sm.state in (State.TRANSCRIBING, State.INJECTING, State.IDLE)
        print(("PASS " if ok2 else "FAIL ") + f"再按一次 -> 结束录音（当前 {ctl.sm.state.value}）")
        ok = ok and ok2

    ctl.shutdown()
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
