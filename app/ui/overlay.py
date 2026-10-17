"""底部悬浮状态窗。

核心要求：**显示但不夺焦点**。
用 Qt.WindowDoesNotAcceptFocus + WA_ShowWithoutActivating，
并设为鼠标穿透——它只是块玻璃，永远不会把光标从你的编辑器里抢走。
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

_STYLE = {
    "recording": ("#E24B4A", "录音中 · 请说话"),
    "transcribing": ("#378ADD", "识别中"),
    "injecting": ("#1D9E75", "已写入"),
    "error": ("#E24B4A", "出错了"),
    "done": ("#1D9E75", "完成"),
    # 空标签 = 主标题直接用调用方传入的文字
    "notice": ("#378ADD", ""),
}


class Overlay(QWidget):
    sig_state = Signal(str, str)
    sig_level = Signal(float)

    def __init__(self, offset_bottom: int = 72, opacity: float = 0.94) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._w, self._h = 300, 62
        self.resize(self._w, self._h)
        self._offset_bottom = offset_bottom
        self._opacity = opacity

        self._state = "idle"
        self._text = ""
        self._level = 0.0
        self._smooth = 0.0
        self._t0 = time.monotonic()
        self._visible_until = 0.0

        self.sig_state.connect(self._apply_state)
        self.sig_level.connect(self._apply_level)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._font_main = QFont("Microsoft YaHei UI", 10)
        self._font_small = QFont("Microsoft YaHei UI", 8)
        self._reposition()
        # 关键：窗口常驻并预先映射。hide() 会销毁原生窗口，下次 show() 要重新
        # 创建+合成 layered window，这期间屏幕上看不到框（几百毫秒）。
        # 所以空闲时画成全透明，而不是隐藏窗口。
        self.show()

    # ---------------- 对外接口（任意线程可调用）----------------
    def set_state(self, state: str, text: str = "") -> None:
        self.sig_state.emit(state, text)

    def set_level(self, level: float) -> None:
        self.sig_level.emit(level)

    def flash(self, text: str, state: str = "injecting", ms: int = 1100) -> None:
        self.sig_state.emit(state, text)
        self._visible_until = time.monotonic() + ms / 1000.0

    def notice(self, text: str, ms: int = 3000) -> None:
        """显示一条自定义提示（主标题就是 text），到时自动收起。"""
        self.flash(text, "notice", ms)

    # ---------------- 内部 ----------------
    def _apply_state(self, state: str, text: str) -> None:
        prev = self._state
        self._state = state
        self._text = text
        if state == "recording" and prev != "recording":
            self._t0 = time.monotonic()
        if state == "idle":
            # 不 hide，只重绘成透明——窗口保持存活，下次显示才是瞬时的
            self.repaint()
            return
        self._reposition()
        if not self.isVisible():
            self.show()
        self.repaint()

    def _apply_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        target = min(1.0, self._level * 6.0)
        self._smooth += (target - self._smooth) * 0.35
        if self._state == "idle":
            return
        if self._visible_until and time.monotonic() > self._visible_until:
            self._visible_until = 0.0
            self.sig_state.emit("idle", "")
            return
        self.update()

    def _reposition(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self._w) // 2
        y = geo.y() + geo.height() - self._h - self._offset_bottom
        self.setGeometry(x, y, self._w, self._h)

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # 窗口常驻，所以空闲态必须真的画成全透明。
        # 必须用 Source 合成模式铺一层全透明——默认的 SourceOver 是"叠加"，
        # 透明像素叠不上去，上一帧的圆角框会留在 layered window 上变成残影。
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self._state == "idle":
            p.end()
            return

        color_hex, label = _STYLE.get(self._state, ("#888780", ""))
        accent = QColor(color_hex)
        if not label:
            label = self._text  # notice 状态：调用方文字直接当主标题

        bg = QColor(24, 24, 28)
        bg.setAlphaF(self._opacity)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self._w - 1, self._h - 1, 14, 14)
        p.fillPath(path, bg)
        p.setPen(QColor(255, 255, 255, 26))
        p.drawPath(path)

        # 状态点：录音时呼吸
        cx, cy = 24, 24
        radius = 5.0
        if self._state == "recording":
            pulse = 0.5 + 0.5 * math.sin((time.monotonic() - self._t0) * 6.0)
            halo = QColor(accent)
            halo.setAlphaF(0.18 + 0.22 * pulse)
            p.setBrush(halo)
            p.setPen(Qt.NoPen)
            p.drawEllipse(int(cx - 9), int(cy - 9), 18, 18)
            radius = 4.5 + 1.2 * pulse
        p.setBrush(accent)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))

        # 状态文字
        p.setPen(QColor(245, 245, 247))
        p.setFont(self._font_main)
        p.drawText(42, 18, self._w - 90, 16, Qt.AlignLeft | Qt.AlignVCenter, label)

        # 计时 / 副文本
        p.setPen(QColor(160, 160, 168))
        p.setFont(self._font_small)
        if self._state == "recording":
            secs = time.monotonic() - self._t0
            p.drawText(self._w - 64, 14, 52, 14, Qt.AlignRight | Qt.AlignVCenter,
                       f"{int(secs // 60):02d}:{int(secs % 60):02d}")
        elif self._text and self._state != "notice":
            p.drawText(self._w - 120, 14, 108, 14, Qt.AlignRight | Qt.AlignVCenter, self._text)

        # 电平条：12 根竖条
        bars = 12
        bar_w, gap = 5, 3
        total = bars * bar_w + (bars - 1) * gap
        start_x = (self._w - total) // 2
        base_y = self._h - 16
        for i in range(bars):
            # 中间高两侧低，形成波形感
            falloff = 1.0 - abs(i - (bars - 1) / 2) / ((bars - 1) / 2 + 1)
            h = 2 + self._smooth * 14 * falloff
            x = start_x + i * (bar_w + gap)
            c = QColor(accent)
            c.setAlphaF(0.35 + 0.6 * min(1.0, self._smooth * 1.4))
            p.setBrush(c)
            p.drawRoundedRect(x, int(base_y - h), bar_w, max(2, int(h)), 2, 2)

        p.end()
