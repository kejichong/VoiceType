"""悬浮球：点一下开始录音，再点一下结束。

为什么要有它：键盘上"好按"的组合键基本被系统占满了 ——
Ctrl+空格 是输入法中英切换、Alt+空格 是系统窗口菜单、Shift+空格 是全角半角，
而 Alt+字母 是各软件菜单栏的快捷键。剩下能用的就只有三键组合，按起来费劲。
屏幕上一个点一下就行的球，比任何组合键都直接。

**唯一真正的技术难点是：点了它以后，电脑的前台窗口不能变成它自己。**

这个程序是靠"按下那一刻的前台窗口"决定把文字贴到哪里去的。
如果点球的时候 Windows 把前台切给了球，文字就会贴进这个球里 —— 用户看到的是
"球变了颜色，但一个字都没进来"，比不能点还糟。

所以窗口必须带 WS_EX_NOACTIVATE（Qt 里写作 Qt.WindowDoesNotAcceptFocus）：
带这个扩展样式的窗口被点击时不会成为前台窗口，焦点留在原来的编辑器里。
光靠它还不够稳妥（不同 Windows 版本行为有细微差异），Controller 那边还持续
跟踪"上一个不是我们自己的前台窗口"作为第二道保险。

画法要点：画布必须比看得见的球**大一圈**。外面那圈透明留白是给阴影和录音光晕用的
——旧版画布只有球那么大，光晕画在 (-3,-3,s+6,s+6) 上直接被裁掉，等于没画。
图标一律用浮点坐标，48px 上用 int() 取整会让图形明显歪。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QMenu, QWidget

_BALL_PAD = 10     # 画布四周留白，给阴影和光晕
_BALL_R = 24       # 球的半径（设计基准）
_SIZE = _BALL_R * 2 + _BALL_PAD * 2      # 68

_BG_IDLE = QColor("#2E333C")
_BG_STATE = {
    "recording": QColor("#E24B4A"),
    "transcribing": QColor("#378ADD"),
    "injecting": QColor("#1D9E75"),
    "done": QColor("#1D9E75"),
    "error": QColor("#E24B4A"),
}
_DRAG_THRESHOLD = 5  # 位移超过这个像素就当拖动，不再算"点了一下"


def _tint(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, color.alphaF() * alpha)))
    return c


class FloatingButton(QWidget):
    sig_clicked = Signal()
    sig_moved = Signal(int, int)

    def __init__(
        self,
        size: int = _SIZE,
        opacity_idle: float = 0.68,
        on_settings=None,
        on_hide=None,
        on_quit=None,
    ) -> None:
        super().__init__(None)
        self._size = size
        self._opacity_idle = opacity_idle
        self._on_settings = on_settings
        self._on_hide = on_hide
        self._on_quit = on_quit

        self._state = "idle"
        self._hover = False
        self._press_global = QPoint()
        self._press_window = QPoint()
        self._dragged = False

        # 关键的两个标志：DoesNotAcceptFocus 让点击不激活本窗口，
        # Tool 让它不进任务栏和 Alt+Tab。缺了前者，这个功能就是废的。
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("语音输入 · 悬浮球")
        self.setFixedSize(size, size)
        self.setToolTip("点一下开始录音，再点一下结束（可拖动，右键有菜单）")

        # 录音时让外圈呼吸，否则静止的球看起来像"没反应"
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------- 对外 ----------------
    def set_state(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self.update()

    # ---------------- 状态与绘制 ----------------
    def _tick(self) -> None:
        if self._state in ("recording", "transcribing"):
            self.update()

    def _alpha(self) -> float:
        if self._state in ("recording", "transcribing", "injecting"):
            return 0.98
        return 1.0 if self._hover else self._opacity_idle

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        self._paint_to(p, self._size)
        p.end()

    def _paint_to(self, p: QPainter, size: int) -> None:
        """把球画到任意 QPainter 上，不局限于本窗口。

        抽出来是为了可测：QWidget.grab() 和 render() 都会先把 widget 背景铺成
        不透明的 Qt 默认灰(227,227,227)，透明通道全丢 —— 于是"球外一圈有没有
        光晕"这种判断会恒成立，测试就失去意义了。对一张透明 QImage 直接作画
        才拿得到真实 alpha。
        """
        s = size
        c = s / 2.0
        k = s / float(_SIZE)          # 缩放系数，画布尺寸可变时图标跟着变
        r = _BALL_R * k
        left = c - r

        p.setRenderHint(QPainter.Antialiasing, True)
        # 透明窗口必须先清屏。默认的 SourceOver 是叠加语义，透明像素叠不上去，
        # 上一帧会留在 layered window 上变成残影。
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setPen(Qt.NoPen)

        alpha = self._alpha()
        base = QColor(_BG_STATE.get(self._state, _BG_IDLE))
        if self._hover and self._state == "idle":
            base = base.lighter(118)

        active = self._state in ("recording", "transcribing")

        # 1) 呼吸光晕。必须画在球外面，靠 _BALL_PAD 留出的那圈透明画布
        if active:
            pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 5.0)
            for grow, a in ((1.16, 0.22), (1.34, 0.11)):
                rr = r * grow
                halo = QColor(base)
                halo.setAlphaF(a * (0.35 + 0.65 * pulse))
                p.setBrush(halo)
                p.drawEllipse(c - rr, c - rr, rr * 2, rr * 2)

        # 2) 投影。几层由外向内逐渐加深的圆，模拟模糊；整体下移一点
        for i in range(6):
            t = i / 5.0
            pad = (5.5 - t * 4.4) * k
            shade = QColor(0, 0, 0)
            shade.setAlphaF((0.016 + t * 0.082) * alpha)
            p.setBrush(shade)
            p.drawEllipse(
                left - pad, left - pad + 1.8 * k, r * 2 + pad * 2, r * 2 + pad * 2
            )

        # 3) 球体。焦点偏左上的径向渐变，纯色填充会显得很扁。
        # 注意参数顺序是 (中心x, 中心y, 中心半径, 焦点x, 焦点y, 焦点半径)：
        # 中心圆必须是那个大的，焦点圆是小的且偏左上，高光才会落在左上方。
        # 写反了（中心半径 0.10、焦点半径 1.08）渐变会退化，整个球变成一坨黑。
        grad = QRadialGradient(c, c, r * 1.04, c - r * 0.34, c - r * 0.40, r * 0.08)
        grad.setColorAt(0.00, _tint(base.lighter(145), alpha))
        grad.setColorAt(0.52, _tint(base, alpha))
        grad.setColorAt(1.00, _tint(base.darker(128), alpha))
        p.setBrush(grad)
        p.drawEllipse(left, left, r * 2, r * 2)

        # 4) 顶部一道高光弧，把球面撑起来
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, int(52 * alpha)), 1.2 * k))
        p.drawArc(
            left + 1.3 * k, left + 1.3 * k,
            r * 2 - 2.6 * k, r * 2 - 2.6 * k,
            205 * 16, 130 * 16,
        )

        # 5) 图标
        ink = QColor(255, 255, 255, int((240 if self._hover else 234) * alpha))
        p.setPen(Qt.NoPen)
        p.save()
        p.translate(c, c)
        p.scale(k, k)
        if self._state == "recording":
            stop = QPainterPath()
            stop.addRoundedRect(-5.6, -5.6, 11.2, 11.2, 2.9, 2.9)
            p.fillPath(stop, ink)
        else:
            self._draw_mic(p, ink)
        p.restore()

    @staticmethod
    def _draw_mic(p: QPainter, ink: QColor) -> None:
        """麦克风图标。原点在球心，单位是设计像素（画布 68、球半径 24 时的像素）。

        全部用浮点坐标，不要 int() —— 48px 上取整误差累积会让图形明显歪。
        """
        p.setPen(Qt.NoPen)
        p.setBrush(ink)

        head = QPainterPath()
        head.addRoundedRect(-4.5, -12.2, 9.0, 15.0, 4.5, 4.5)   # 话筒头（胶囊）
        p.fillPath(head, ink)

        # 托住话筒的 U 形弧：开口 220°，两端正好接到话筒头底部
        pen = QPen(ink, 1.9)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(-8.2, -8.45, 16.4, 16.4, 160 * 16, 220 * 16)

        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        p.drawRoundedRect(-0.85, 6.4, 1.7, 4.1, 0.85, 0.85)     # 支架
        p.drawRoundedRect(-6.0, 10.2, 12.0, 2.2, 1.1, 1.1)      # 底座

    # ---------------- 鼠标 ----------------
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._press_global = event.globalPosition().toPoint()
        self._press_window = self.pos()
        self._dragged = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._press_global.isNull():
            now = event.globalPosition().toPoint()
            delta = now - self._press_global
            if delta.manhattanLength() > _DRAG_THRESHOLD:
                self._dragged = True
                self.move(self._press_window + delta)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        was_dragged = self._dragged
        self._press_global = QPoint()
        self._dragged = False
        if was_dragged:
            self.sig_moved.emit(self.x(), self.y())
        else:
            self.sig_clicked.emit()
        event.accept()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_settings = menu.addAction("设置…")
        act_hide = menu.addAction("隐藏这个球")
        menu.addSeparator()
        act_quit = menu.addAction("退出语音输入")
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen == act_settings and self._on_settings:
            self._on_settings()
        elif chosen == act_hide and self._on_hide:
            self._on_hide()
        elif chosen == act_quit and self._on_quit:
            self._on_quit()
