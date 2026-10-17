"""端到端：真点一下悬浮球，看文字有没有真的进到编辑器里。

前面 smoke_floatbtn 只证明了"点击不抢焦点"和"点击能触发"，
但这个功能的成败只有一条标准：**文字进没进到你正在打字的地方**。
所以这里用离线假引擎跑完整链路：点球开始 → 等一会 → 再点球结束 →
识别(mock) → 注入，最后检查目标编辑器的内容。
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
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]
LEFT_DOWN, LEFT_UP = 0x0002, 0x0004

OUT = ROOT / ".venv" / "e2e_floatbtn.txt"
lines: list[str] = []


def log(msg: str) -> None:
    lines.append(msg)
    print(msg)


def pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def click_at(app, point) -> None:
    """把光标移过去并真按一下鼠标左键。

    必须用原生鼠标事件：Qt 合成的点击不经过 Windows 的窗口激活路径，
    测不出"点了以后焦点跑哪去了"这个真正的问题。
    """
    from PySide6.QtGui import QCursor
    QCursor.setPos(point)
    pump(app, 120)
    user32.mouse_event(LEFT_DOWN, 0, 0, 0, None)
    time.sleep(0.04)
    user32.mouse_event(LEFT_UP, 0, 0, 0, None)


def main() -> int:
    (HOME / "config.json").write_text(json.dumps({
        "engine": {"type": "mock"},
        "hotkey": {"binding": "Ctrl+Alt+Shift+F11"},
        "ui": {"float_button": True, "float_pos": [600, 400]},
        "injection": {"delay_sec": 0.4},
    }, ensure_ascii=False), encoding="utf-8")

    from PySide6.QtWidgets import QApplication, QTextEdit

    from app.config import Config
    from app.main import Controller

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    target = QTextEdit()
    target.setWindowTitle("悬浮球端到端 · 目标编辑器")
    target.resize(560, 220)
    target.move(120, 120)
    target.show()
    target.raise_()
    target.activateWindow()
    pump(app, 400)

    cfg = Config.load()
    ctl = Controller(cfg)
    ctl.start()
    pump(app, 500)

    btn = ctl.fbtn
    if btn is None:
        log("FAIL 悬浮球没有创建出来")
        return 1
    if not btn.isVisible():
        log("FAIL 悬浮球没有显示")
        return 1
    log(f"悬浮球已就位：({btn.x()}, {btn.y()}) 目标编辑器 hwnd={int(target.winId()):#x}")
    log(f"主控当前跟踪的前台窗口 = {ctl._last_foreground:#x}")

    ok_target = ctl._last_foreground == int(target.winId())
    log(("PASS " if ok_target else "FAIL ") + "主控跟踪到的前台窗口就是目标编辑器")

    # 第一次点击：开始录音
    click_at(app, btn.geometry().center())
    pump(app, 700)
    log(f"第一次点击后状态 = {ctl.sm.state.value}，悬浮球状态 = {btn._state}")
    ok_started = ctl.sm.state.value == "recording"
    log(("PASS " if ok_started else "FAIL ") + "点一下就开始录音了")

    # 第二次点击：结束并注入
    pump(app, 900)
    click_at(app, btn.geometry().center())
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        pump(app, 100)
        if target.toPlainText().strip():
            break

    text = target.toPlainText()
    log(f"目标编辑器内容 = {text!r}")
    ok_text = bool(text.strip())
    log(("PASS " if ok_text else "FAIL ") + "文字真的进了目标编辑器（不是进了悬浮球）")

    # 文字刚出现时状态机还在 injecting，要给它收尾的时间
    pump(app, 600)
    ok_final = ctl.sm.state.value == "idle"
    log(("PASS " if ok_final else "FAIL ") + f"回到空闲状态（当前 {ctl.sm.state.value}）")

    ok = ok_target and ok_started and ok_text and ok_final
    log("RESULT: " + ("OK" if ok else "FAIL"))
    OUT.write_text("\n".join(lines), encoding="utf-8")
    ctl.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
