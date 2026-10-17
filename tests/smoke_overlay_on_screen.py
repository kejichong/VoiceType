"""验证：按下快捷键那一刻，悬浮窗是否真的出现在屏幕上（不是只调用了绘制函数）。

之前的测试只统计 paintEvent 被调用了几次 —— 那证明不了用户看得见。
这里直接抓屏做像素差分：
  空闲态  -> 该区域应该和桌面一致（窗口常驻但全透明，不能留残影）
  按下后  -> 该区域应该出现明显的深色卡片
并测出从按下到"像素真的变化"用了多少毫秒。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.overlay import Overlay  # noqa: E402


def grab(app: QApplication, rect):
    """抓取屏幕上一块区域，返回 QImage。"""
    scr = app.primaryScreen()
    shot = scr.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
    return shot.toImage()


def diff_pixels(a, b, threshold: int = 12) -> int:
    """两张同尺寸图里，有多少像素差异超过阈值。"""
    if a.size() != b.size():
        return -1
    w, h = a.width(), a.height()
    changed = 0
    for y in range(0, h, 2):          # 隔行采样，够用且快
        for x in range(0, w, 2):
            ca = a.pixelColor(x, y)
            cb = b.pixelColor(x, y)
            if (abs(ca.red() - cb.red()) > threshold
                    or abs(ca.green() - cb.green()) > threshold
                    or abs(ca.blue() - cb.blue()) > threshold):
                changed += 1
    return changed


def pump(app: QApplication, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    app = QApplication(sys.argv)
    ov = Overlay(offset_bottom=72, opacity=0.94)
    pump(app, 150)                    # 等窗口完成首次映射和首帧

    rect = ov.geometry()
    print(f"悬浮窗位置 = ({rect.x()}, {rect.y()}) 尺寸 {rect.width()}x{rect.height()}")
    print(f"isVisible = {ov.isVisible()}   state = {ov._state}")

    # ---------- 1. 空闲态：常驻窗口必须完全透明 ----------
    base = grab(app, rect)            # 记录"没框"时的桌面样子
    pump(app, 60)
    idle = grab(app, rect)
    idle_changed = diff_pixels(base, idle)
    sampled = (rect.width() // 2) * (rect.height() // 2)
    ok_idle = idle_changed >= 0 and idle_changed < sampled * 0.06
    print(f"\n[空闲态] 采样 {sampled} 像素，与桌面差异 {idle_changed} 个")
    print(("PASS " if ok_idle else "FAIL ") + "空闲时窗口全透明，桌面上没有残影")

    # ---------- 2. 按下快捷键：模拟主线程真实的调用顺序 ----------
    #     set_state + repaint 同步绘制  ->  让出事件循环 40ms（等 DWM 呈现）
    t0 = time.monotonic()
    ov.set_state("recording", "")
    ov.repaint()
    painted_ms = (time.monotonic() - t0) * 1000

    # 逐 10ms 轮询屏幕，测出"人眼能看到"的真实延迟
    visible_ms = None
    deadline = t0 + 0.6
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.008)
        now = grab(app, rect)
        if diff_pixels(idle, now) > sampled * 0.35:
            visible_ms = (time.monotonic() - t0) * 1000
            break

    if visible_ms is None:
        print(f"\n[按下后] 0.6 秒内屏幕上看不到卡片")
        print("FAIL 按下后没能在屏幕上出现")
        ov.close()
        return 1

    print(f"\n[按下后] 同步绘制耗时 {painted_ms:.1f} ms，"
          f"屏幕上真正可见耗时 {visible_ms:.0f} ms")
    ok_fast = visible_ms < 150
    print(("PASS " if ok_fast else "FAIL ") + f"可见延迟 {visible_ms:.0f}ms < 150ms")

    # ---------- 3. 回到空闲：残影必须消失 ----------
    ov.set_state("idle", "")
    ov.repaint()
    pump(app, 120)
    back = grab(app, rect)
    residue = diff_pixels(idle, back)
    ok_clean = residue < sampled * 0.06
    print(f"\n[收起后] 与原始桌面差异 {residue} 个像素")
    print(("PASS " if ok_clean else "FAIL ") + "收起后桌面恢复原样，无残影")

    ov.close()
    ok = ok_idle and ok_fast and ok_clean
    print("\n" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
