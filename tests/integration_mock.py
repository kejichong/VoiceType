"""整体编排测试：用离线假引擎跑完整链路。

覆盖 Controller 的状态编排：热键事件 → 开始录音 → 停止 → 识别(mock)
→ 后处理 → 注入 → 状态回 IDLE。不联网、不需要真实密钥。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".venv" / "testhome"
HOME.mkdir(parents=True, exist_ok=True)
os.environ["VOICETYPE_HOME"] = str(HOME)
sys.path.insert(0, str(ROOT))

OUT = ROOT / ".venv" / "integration.txt"
lines: list[str] = []


def log(msg: str) -> None:
    lines.append(msg)


def flush(result: str) -> None:
    log(f"RESULT: {result}")
    OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    try:
        (HOME / "config.json").write_text(json.dumps({
            "engine": {"type": "mock"},
            "hotkey": {"binding": "Ctrl+Alt+Shift+F11"},
            "injection": {"delay_sec": 0.4},
        }, ensure_ascii=False), encoding="utf-8")

        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QTextEdit

        from app.config import Config
        from app.main import Controller
        from app.state import State

        app = QApplication(sys.argv[:1])
        app.setQuitOnLastWindowClosed(False)

        target = QTextEdit()
        target.setWindowTitle("VoiceType 编排测试")
        target.resize(560, 220)
        target.show()
        target.raise_()
        target.activateWindow()

        cfg = Config.load()
        log(f"引擎类型: {cfg.get('engine.type')}")
        ctl = Controller(cfg)
        ctl.start()
        log(f"热键已注册: {ctl.hotkey is not None}")
        app.processEvents()

        marks = {"t0": 0.0}

        def pump(ms: int) -> None:
            import time as _t
            end = _t.monotonic() + ms / 1000.0
            while _t.monotonic() < end:
                app.processEvents()
                _t.sleep(0.005)

        def begin() -> None:
            log(f"开始录音前状态: {ctl.sm.state.value}")
            ctl.toggle()
            # 开设备被故意推迟了 40ms（先让悬浮窗画到屏幕上），
            # 这里得把事件循环跑起来，否则读到的还是 idle。
            pump(150)
            log(f"开始录音后状态: {ctl.sm.state.value}")

        def stop() -> None:
            log(f"停止前状态: {ctl.sm.state.value}")
            ctl.toggle()
            log(f"停止后状态: {ctl.sm.state.value}")

        def verify() -> None:
            text = target.toPlainText()
            log(f"最终状态: {ctl.sm.state.value}")
            log(f"目标框内容: {text!r}")
            ok = bool(text.strip()) and ctl.sm.state == State.IDLE
            log(f"是否贴入文字: {bool(text.strip())}")
            log(f"是否回到 IDLE: {ctl.sm.state == State.IDLE}")
            flush("OK" if ok else "FAIL")
            ctl.shutdown()

        QTimer.singleShot(700, begin)
        QTimer.singleShot(2100, stop)
        QTimer.singleShot(4200, verify)
        QTimer.singleShot(7000, lambda: (flush("FAIL - 超时"), app.quit()))
        app.exec()

        if not OUT.exists():
            flush("FAIL - 未完成")
            return 1
        return 0
    except Exception:
        log(traceback.format_exc())
        flush("FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
