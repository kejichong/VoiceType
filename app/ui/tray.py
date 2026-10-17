"""系统托盘：功能入口与状态可见性。

悬浮窗是鼠标穿透的，所以所有交互动作（设置、退出、手动开始/停止）
都放在托盘菜单里，避免为了点按钮去抢焦点。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

_COLORS = {
    "idle": "#5F5E5A",
    "recording": "#E24B4A",
    "transcribing": "#378ADD",
    "error": "#E24B4A",
}


def make_icon(state: str = "idle") -> QIcon:
    """画一个话筒图标，颜色随状态变化（不需要外部图片资源）。"""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    bg = QColor(_COLORS.get(state, "#5F5E5A"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(2, 2, size - 4, size - 4), 16, 16)
    p.fillPath(path, bg)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawRoundedRect(QRectF(26, 14, 12, 22), 6, 6)      # 话筒头
    p.drawRoundedRect(QRectF(29, 36, 6, 8), 2, 2)        # 支架
    p.drawRoundedRect(QRectF(22, 43, 20, 3.5), 2, 2)     # 底座
    p.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        on_toggle,
        on_settings,
        on_quit,
        on_reload,
        on_toggle_float=None,
        float_visible: bool = True,
    ) -> None:
        super().__init__(make_icon("idle"))
        self._on_toggle = on_toggle
        self._on_settings = on_settings
        self._state = "idle"
        self._state_text = "就绪"

        menu = QMenu()
        self._act_toggle = QAction("开始录音", menu)
        self._act_toggle.triggered.connect(lambda: self._on_toggle())
        menu.addAction(self._act_toggle)

        # 球的入口。它平时是半透明的，用户一时找不到时，右键托盘要能一眼看到
        # 并把它叫回来 —— 否则唯一的恢复入口埋在设置窗口里，等于没有。
        self._act_float = QAction("显示悬浮球", menu)
        self._act_float.setCheckable(True)
        self._act_float.setChecked(float_visible)
        if on_toggle_float is not None:
            self._act_float.triggered.connect(
                lambda checked: on_toggle_float(checked)
            )
        menu.addAction(self._act_float)

        menu.addSeparator()
        act_settings = QAction("设置…", menu)
        act_settings.triggered.connect(lambda: on_settings())
        menu.addAction(act_settings)

        act_reload = QAction("重新加载配置", menu)
        act_reload.triggered.connect(lambda: on_reload())
        menu.addAction(act_reload)

        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(lambda: on_quit())
        menu.addAction(act_quit)

        self._menu = menu
        self.setContextMenu(menu)
        self.setToolTip("语音输入 · 就绪")
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        # 点图标 = 打开设置窗口。录音是热键或菜单的事——
        # 点一下就开录太容易误触，而且用户点图标本来是想"看看这个程序"。
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_settings()

    def set_state(self, state: str, text: str = "") -> None:
        self._state = state
        self.setIcon(make_icon(state))
        recording = state == "recording"
        self._act_toggle.setText("停止录音" if recording else "开始录音")
        self._state_text = text or {
            "idle": "就绪", "recording": "录音中",
            "transcribing": "识别中", "error": "出错了",
        }.get(state, state)
        self.setToolTip(f"语音输入 · {self._state_text}")

    def set_float_visible(self, visible: bool) -> None:
        """主控单向同步勾选状态（设置窗口里改了开关也要跟着变）。

        必须屏蔽信号：setChecked 会触发 triggered，进而回调主控，
        主控又调回来同步，形成来回抖动。
        """
        if self._act_float.isChecked() == visible:
            return
        self._act_float.blockSignals(True)
        self._act_float.setChecked(visible)
        self._act_float.blockSignals(False)

    def notify(self, title: str, message: str, ms: int = 3000) -> None:
        self.showMessage(title, message, make_icon("error"), ms)
