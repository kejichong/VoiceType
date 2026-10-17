"""把悬浮球各状态渲染成一张对比图，用来检查外观。

美观这事没法靠断言，只能画出来看。放大 3 倍，否则 68px 上根本看不清细节。
背景铺成浅色和深色两段，因为球是半透明的，在两种底色上表现不一样。
"""
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parent.parent / ".venv" / "diag"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ui.floatbtn import FloatingButton  # noqa: E402

STATES = [
    ("idle", False, "空闲"),
    ("idle", True, "鼠标悬停"),
    ("recording", False, "录音中"),
    ("transcribing", False, "识别中"),
    ("done", False, "完成"),
]
ZOOM = 3
BG_LIGHT = QColor("#EDEFF2")
BG_DARK = QColor("#1B1D21")


def main() -> int:
    app = QApplication(sys.argv)

    btn = FloatingButton()
    size = btn.width()

    cols = len(STATES)
    rows = 2
    cell_w, cell_h = size * ZOOM + 40, size * ZOOM + 56
    canvas = QImage(cell_w * cols, cell_h * rows, QImage.Format_RGB32)

    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)

    for row, bg in enumerate((BG_LIGHT, BG_DARK)):
        for col, (state, hover, label) in enumerate(STATES):
            ox, oy = col * cell_w, row * cell_h
            p.fillRect(ox, oy, cell_w, cell_h, bg)

            btn._state = state
            btn._hover = hover
            # 不能用 grab()/render() —— 它们会把 widget 背景铺成不透明的 Qt 默认灰，
            # 半透明效果就全看不出来了。画到透明画布上再叠到底色上。
            shot = QImage(btn.width(), btn.height(), QImage.Format_ARGB32)
            shot.fill(QColor(0, 0, 0, 0))
            pp = QPainter(shot)
            btn._paint_to(pp, btn.width())
            pp.end()
            big = shot.scaled(
                shot.width() * ZOOM, shot.height() * ZOOM,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            p.drawImage(ox + (cell_w - big.width()) // 2, oy + 18, big)

            p.setPen(QColor("#8A8A85") if bg == BG_LIGHT else QColor("#9A9A95"))
            p.drawText(
                ox, oy + cell_h - 22, cell_w, 20,
                Qt.AlignHCenter | Qt.AlignVCenter, label,
            )

    # 中间一道分隔线，标出浅底 / 深底
    p.setPen(QColor("#C8C8C4"))
    p.drawLine(0, cell_h, canvas.width(), cell_h)
    p.end()

    out = OUT / "ball_states.png"
    canvas.save(str(out))
    print(f"已保存 {out}（{canvas.width()}x{canvas.height()}）")
    print("上排=浅色桌面底色，下排=深色桌面底色")
    btn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
