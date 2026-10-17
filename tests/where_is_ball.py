"""生成一张"悬浮球在哪"的标注图：全屏缩略 + 球位置画圈 + 放大特写拼在右下角。

坐标来源是 Windows 的 GetWindowRect（物理像素），不是配置里推算的，
所以不会有 dpr 换算错位的问题。
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).resolve().parent.parent / ".venv" / "diag"
OUT.mkdir(parents=True, exist_ok=True)

TITLE_PREFIX = "语音输入 · 悬浮球"
SCALE = 0.5          # 物理 -> 输出图

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_ball() -> list[tuple[int, tuple[int, int, int, int]]]:
    found: list[tuple[int, tuple[int, int, int, int]]] = []

    @WNDENUMPROC
    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith(TITLE_PREFIX):
            r = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                if (r.right - r.left) > 10 and (r.bottom - r.top) > 10:
                    found.append((int(hwnd), (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(cb, 0)
    return found


def main() -> int:
    app = QApplication(sys.argv)
    balls = find_ball()
    if not balls:
        print("没找到悬浮球窗口——程序没在跑，或设置里把球关了")
        return 1

    l, t, r, b = balls[0][1]
    raw = app.primaryScreen().grabWindow(0).toImage()

    base = raw.scaled(
        int(raw.width() * SCALE), int(raw.height() * SCALE),
        Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
    )
    W, H = base.width(), base.height()

    canvas = QImage(base)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)

    # 球在输出图上的矩形
    cx, cy = int((l + r) / 2 * SCALE), int((t + b) / 2 * SCALE)
    radius = int(58)

    # 半透明暗化全屏，把球衬出来
    p.fillRect(0, 0, W, H, QColor(0, 0, 0, 70))

    pen = QPen(QColor("#FF2D2D"))
    pen.setWidth(5)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
    pen.setWidth(8)
    p.setPen(pen)
    p.drawEllipse(cx - radius - 14, cy - radius - 14, (radius + 14) * 2, (radius + 14) * 2)

    # 引线往左上拉，避开右下角的特写小图
    pen.setWidth(4)
    p.setPen(pen)
    ex, ey = cx - int(radius * 0.72), cy - int(radius * 0.72)
    p.drawLine(ex, ey, ex - 150, ey - 90)
    p.drawLine(ex - 150, ey - 90, ex - 420, ey - 90)

    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(26)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#FF2D2D"))
    p.drawText(
        QRect(ex - 760, ey - 132, 350, 44),
        Qt.AlignRight | Qt.AlignVCenter,
        "悬浮球在这里（点一下开始录音）",
    )

    # 右下角贴放大特写
    pad = 60
    crop = raw.copy(QRect(l - pad, t - pad, (r - l) + pad * 2, (b - t) + pad * 2))
    thumb = crop.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    tx, ty = W - thumb.width() - 26, H - thumb.height() - 26
    p.fillRect(tx - 8, ty - 8, thumb.width() + 16, thumb.height() + 16, QColor(20, 20, 20, 200))
    p.drawImage(tx, ty, thumb)
    p.setPen(QPen(QColor("#FF2D2D"), 3))
    p.drawRect(tx - 8, ty - 8, thumb.width() + 16, thumb.height() + 16)

    font.setPixelSize(19)
    font.setBold(False)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(
        QRect(tx - 130, ty - 40, thumb.width() + 260, 30),
        Qt.AlignRight | Qt.AlignVCenter,
        "放大后长这样",
    )
    p.end()

    out = OUT / "where_is_ball.png"
    canvas.save(str(out))
    print(f"屏幕 {raw.width()}x{raw.height()} 物理，输出 {W}x{H}")
    print(f"球物理矩形 ({l},{t})-({r},{b})，输出图中心 ({cx},{cy})")
    print(f"横向 {cx / W * 100:.0f}%、纵向 {cy / H * 100:.0f}%")
    print(f"已保存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
