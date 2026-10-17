"""界面与热键冒烟测试：验证 Qt 部分能否真正工作。

结果直接写文件（避免控制台编码把中文弄乱）。
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / ".venv" / "smoke.txt"
lines: list[str] = []


def log(msg: str) -> None:
    lines.append(msg)


def flush() -> None:
    OUT.write_text("\n".join(lines), encoding="utf-8")


TEST_BINDING = "Ctrl+Alt+Shift+F12"


def main() -> int:
    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication

        from app.hotkey import HotkeyManager
        from app.ui.overlay import Overlay
        from app.ui.tray import Tray, make_icon

        app = QApplication(sys.argv[:1])
        log(f"Qt 平台: {app.platformName()}")
        scr = QGuiApplication.primaryScreen()
        if scr:
            g = scr.geometry()
            log(f"屏幕: {g.width()}x{g.height()} @ DPI {scr.devicePixelRatio():.2f}")
            log(f"可用区域: {scr.availableGeometry()}")

        # ---- 悬浮窗 ----
        ov = Overlay(offset_bottom=72, opacity=0.94)
        flags = ov.windowFlags()
        log(f"悬浮窗 NoFocus={bool(flags & Qt.WindowDoesNotAcceptFocus)}")
        log(f"悬浮窗 鼠标穿透={bool(flags & Qt.WindowTransparentForInput)}")
        log(f"悬浮窗 置顶={bool(flags & Qt.WindowStaysOnTopHint)}")
        log(f"悬浮窗 Tool={bool(flags & Qt.Tool)}")
        ov.set_state("recording", "")
        ov.show()
        log(f"悬浮窗 可见={ov.isVisible()} 几何={ov.geometry().getRect()}")
        ov.set_level(0.6)

        # ---- 托盘图标 ----
        icon = make_icon("recording")
        log(f"图标生成 非空={not icon.isNull()}")
        tray = Tray(lambda: None, lambda: None, lambda: None, lambda: None)
        tray.set_state("recording", "录音中")
        tray.show()
        log(f"托盘 可见={tray.isVisible()} 提示={tray.toolTip()}")

        # ---- 热键：注册 + 模拟按键验证 ----
        fired = {"n": 0}

        def on_hotkey() -> None:
            fired["n"] += 1

        mgr = HotkeyManager(on_hotkey)
        try:
            mgr.start(TEST_BINDING)
            log(f"热键注册 {TEST_BINDING} = OK")
        except Exception as exc:
            log(f"热键注册失败: {exc!r}")

        def press() -> None:
            import ctypes
            import time

            VK_CONTROL, VK_MENU, VK_SHIFT, VK_F12 = 0x11, 0x12, 0x10, 0x7B
            u = ctypes.windll.user32
            for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_F12):
                u.keybd_event(vk, 0, 0, 0)
                time.sleep(0.01)
            for vk in (VK_F12, VK_SHIFT, VK_MENU, VK_CONTROL):
                u.keybd_event(vk, 0, 2, 0)
                time.sleep(0.01)

        QTimer.singleShot(400, press)
        QTimer.singleShot(1400, lambda: log(f"热键触发次数={fired['n']}"))
        QTimer.singleShot(1600, lambda: log(f"电平平滑值={ov._smooth:.3f}"))
        QTimer.singleShot(1800, app.quit)
        app.exec()

        mgr.stop()
        ov.hide()
        tray.hide()
        log("RESULT: OK")
        flush()
        return 0
    except Exception:
        log("RESULT: FAIL")
        log(traceback.format_exc())
        flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
