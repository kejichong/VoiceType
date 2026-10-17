"""文本注入：把识别结果送到目标窗口的光标处。

策略（已与需求方确认）：剪贴板粘贴为主。
关键约束：必须无损备份并还原剪贴板，否则会弄丢用户原有的图片/文件。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import win32util as w32

# 目标程序收到 Ctrl+V 后是异步读取剪贴板的，过早还原会导致粘贴失败
_PASTE_SETTLE_SEC = 0.35
_PASTE_SETTLE_LONG_SEC = 0.6
_LONG_TEXT_THRESHOLD = 1500


@dataclass
class InjectResult:
    ok: bool
    reason: str = ""
    clipboard_restored: bool = True
    snapshot_summary: str = ""

    def __bool__(self) -> bool:
        return self.ok


def inject_text(
    text: str,
    target_hwnd: int = 0,
    delay: float | None = None,
    keep_clipboard: bool = False,
) -> InjectResult:
    """把 text 粘贴到 target_hwnd 的光标处。

    target_hwnd 为 0 时使用当前前台窗口。
    keep_clipboard=True 时只写入剪贴板不粘贴（降级模式）。
    """
    if not text:
        return InjectResult(False, "文本为空")

    hwnd = target_hwnd or w32.get_foreground_window()
    if not w32.is_window(hwnd):
        return InjectResult(False, "目标窗口已关闭")

    snapshot = w32.ClipboardSnapshot.capture()
    summary = snapshot.summary()

    if not w32.set_clipboard_text(text):
        return InjectResult(False, "写入剪贴板失败（可能被其他程序占用）", True, summary)

    if keep_clipboard:
        return InjectResult(True, "", True, summary)

    # 焦点可能已漂移（用户点了别的窗口），拉回来再粘贴
    if w32.get_foreground_window() != hwnd:
        if not w32.set_foreground_window(hwnd):
            _safe_restore(snapshot, text)
            return InjectResult(False, "无法把焦点切回目标窗口", True, summary)
        time.sleep(0.05)

    w32.send_ctrl_v()

    settle = delay if delay is not None else (
        _PASTE_SETTLE_LONG_SEC if len(text) > _LONG_TEXT_THRESHOLD else _PASTE_SETTLE_SEC
    )
    time.sleep(settle)

    restored = _safe_restore(snapshot, text)
    return InjectResult(True, "", restored, summary)


def _safe_restore(snapshot: w32.ClipboardSnapshot, injected: str) -> bool:
    """还原剪贴板。

    安全网：如果此刻剪贴板内容已经不是我们写进去的那段文字
    （说明用户在这几百毫秒里自己复制了新东西），就不要还原，
    否则会把用户刚复制的内容覆盖掉。
    """
    current = w32.get_clipboard_text()
    if current is not None and current != injected:
        return True
    return snapshot.restore()


def type_text(text: str) -> InjectResult:
    """模拟逐字键入（备用方案，部分应用中文会丢字）。"""
    if not text:
        return InjectResult(False, "文本为空")
    w32.send_unicode_text(text)
    return InjectResult(True, "type")
