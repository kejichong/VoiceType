"""端到端注入测试：把文字真正贴进一个文本框里。

用本进程创建的 QTextEdit 当目标窗口，验证
「备份剪贴板 → 写剪贴板 → Ctrl+V → 还原剪贴板」整条链路。

注意：注入必须放在工作线程执行（与产品实际路径一致）。
若在主线程同步 sleep，目标窗口的消息循环会被一起堵住，
Ctrl+V 要等剪贴板还原后才被处理，会得到假的失败结果。
"""
from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / ".venv" / "e2e.txt"
lines: list[str] = []


def log(msg: str) -> None:
    lines.append(msg)


def flush(result: str) -> None:
    log(f"RESULT: {result}")
    OUT.write_text("\n".join(lines), encoding="utf-8")


SENTINEL = "剪贴板原有内容-E2E-8848"
PAYLOAD = "这是语音输入测试文字，应该出现在光标位置。"


def main() -> int:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QTextEdit

        from app import injector, win32util as w32

        w32.enable_dpi_awareness()
        w32.set_clipboard_text(SENTINEL)

        app = QApplication(sys.argv[:1])
        edit = QTextEdit()
        edit.setWindowTitle("VoiceType 注入测试")
        edit.resize(520, 200)
        edit.show()
        edit.raise_()
        edit.activateWindow()

        results: queue.Queue = queue.Queue()
        state = {"done": False}

        def worker(hwnd: int) -> None:
            try:
                log("[worker] 开始注入")
                res = injector.inject_text(PAYLOAD, hwnd, delay=0.45)
                log(f"[worker] 返回 ok={res.ok} reason={res.reason!r}")
                results.put(res)
            except Exception as exc:
                log(f"[worker] 异常: {exc!r}")
                results.put(None)

        def start_inject() -> None:
            hwnd = int(edit.winId())
            log(f"目标窗口句柄: {hwnd}")
            log(f"注入前剪贴板: {w32.get_clipboard_text()!r}")
            threading.Thread(target=worker, args=(hwnd,), daemon=True).start()

        def poll() -> None:
            try:
                res = results.get_nowait()
            except queue.Empty:
                return
            if res is None:
                state["done"] = True
                flush("FAIL - worker 抛异常")
                app.quit()
                return
            log(f"注入结果: ok={res.ok} reason={res.reason!r} "
                f"剪贴板还原={res.clipboard_restored}")
            log(f"注入前快照: {res.snapshot_summary}")
            QTimer.singleShot(500, verify)

        def verify() -> None:
            got = edit.toPlainText()
            log(f"文本框内容: {got!r}")
            log(f"粘贴成功: {PAYLOAD in got}")
            after = w32.get_clipboard_text()
            log(f"注入后剪贴板: {after!r}")
            log(f"剪贴板已还原: {after == SENTINEL}")
            ok = PAYLOAD in got and after == SENTINEL
            state["done"] = True
            flush("OK" if ok else "FAIL")
            app.quit()

        poll_timer = QTimer()
        poll_timer.setInterval(100)
        poll_timer.timeout.connect(poll)
        poll_timer.start()

        QTimer.singleShot(600, start_inject)
        QTimer.singleShot(6000, lambda: (not state["done"]) and flush("FAIL - 超时未完成") or app.quit())
        app.exec()

        if not state["done"]:
            flush("FAIL - 未完成")
        return 0 if state["done"] else 1
    except Exception:
        log(traceback.format_exc())
        flush("FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
