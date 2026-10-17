"""验证：按下快捷键那一刻悬浮窗是否已经真的画出来了。

关键点是 repaint() 必须同步绘制，不能只把 show() 排进事件队列——
否则紧接着的 recorder.open() 会阻塞主线程，绘制被卡住，用户看不到框。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.overlay import Overlay  # noqa: E402


class CountOverlay(Overlay):
    paints = 0

    def paintEvent(self, event) -> None:
        type(self).paints += 1
        super().paintEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    ov = CountOverlay(offset_bottom=72, opacity=0.94)
    ov.show()
    app.processEvents()
    CountOverlay.paints = 0

    # 模拟按下快捷键：设状态 -> 同步绘制 -> 立刻检查（不跑事件循环）
    t0 = time.monotonic()
    ov.set_state("recording", "")
    ov.repaint()
    painted = CountOverlay.paints
    cost_ms = (time.monotonic() - t0) * 1000

    print(f"set_state + repaint 用时 {cost_ms:.1f} ms")
    print(f"同步绘制次数 = {painted}")
    print(f"isVisible = {ov.isVisible()}")

    ok_visible = ov.isVisible()
    ok_painted = painted >= 1
    print(("PASS " if ok_visible else "FAIL ") + "按下后窗口立即可见")
    print(("PASS " if ok_painted else "FAIL ") + "按下后已完成一次绘制（不是排队等事件循环）")
    print(("PASS " if cost_ms < 120 else "FAIL ") + f"响应耗时 {cost_ms:.0f}ms < 120ms")

    ov.hide()
    return 0 if (ok_visible and ok_painted and cost_ms < 120) else 1


if __name__ == "__main__":
    sys.exit(main())
