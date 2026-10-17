"""把 Overlay 的 notice 状态渲染成 PNG，肉眼确认文字没被裁掉。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from app.ui.overlay import Overlay  # noqa: E402

OUT = PROJ / ".venv" / "shots"
OUT.mkdir(parents=True, exist_ok=True)

CASES = [
    ("notice_ready", "已就绪 · Ctrl+Alt+Space", "notice", 3200),
    ("notice_first", "首次使用，需要先填阿里云密钥", "notice", 3200),
    ("notice_saved", "设置已保存", "notice", 1800),
    ("recording", "", "recording", 3200),
]


def main() -> int:
    app = QApplication(sys.argv)
    ov = Overlay(offset_bottom=72, opacity=0.94)
    ov.show()
    app.processEvents()

    for name, text, state, ms in CASES:
        ov.flash(text, state, ms)
        app.processEvents()
        pm = ov.grab()
        path = OUT / f"{name}.png"
        pm.save(str(path))
        print(f"{name}: {pm.width()}x{pm.height()} -> {path}")

    ov.hide()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
