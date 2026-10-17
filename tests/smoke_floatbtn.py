"""验证悬浮球最要命的一条：点它之后，前台窗口不能变成它自己。

这个程序靠"按下那一刻的前台窗口"决定把文字贴到哪。点球的瞬间如果 Windows
把前台切给了球，文字就会贴进空气里——用户看到的是"球变颜色了但一个字都没进来"。

所以用**真实鼠标点击**（ctypes 发原生事件）来测，不能用 Qt 的 QTest.mouseClick：
后者是进程内合成事件，根本不经过 Windows 的窗口激活路径，测不出这个问题。

同时验证：单击触发一次 toggle、拖动只移动不触发 toggle、各状态能正常绘制。
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]
user32.mouse_event.restype = None

LEFT_DOWN = 0x0002
LEFT_UP = 0x0004


def click() -> None:
    user32.mouse_event(LEFT_DOWN, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(LEFT_UP, 0, 0, 0, None)


def pump(app, ms: int) -> None:
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication, QTextEdit

    from app.ui.floatbtn import FloatingButton
    from app.win32util import get_foreground_window

    app = QApplication(sys.argv[:1])

    # 一个"用户正在打字的地方"，用来确认焦点没被抢走
    editor = QTextEdit()
    editor.setWindowTitle("悬浮球测试 · 目标编辑器")
    editor.resize(520, 200)
    editor.show()
    editor.raise_()
    editor.activateWindow()
    pump(app, 300)

    btn = FloatingButton()
    clicks: list[int] = []
    moves: list[tuple[int, int]] = []
    btn.sig_clicked.connect(lambda: clicks.append(1))
    btn.sig_moved.connect(lambda x, y: moves.append((x, y)))
    btn.show()
    pump(app, 250)

    ok_all = True

    # ---------- 0. 基本可见性 ----------
    ok_visible = btn.isVisible() and btn.width() > 0
    print(("PASS " if ok_visible else "FAIL ") + f"悬浮球已显示（{btn.width()}x{btn.height()}）")
    ok_all &= ok_visible

    # ---------- 1. 点击不能抢焦点（最关键的一条）----------
    center = btn.geometry().center()
    QCursor.setPos(center)
    pump(app, 120)

    fg_before = get_foreground_window()
    self_hwnd = int(btn.winId())
    click()
    pump(app, 400)
    fg_after = get_foreground_window()

    print(f"\n前台窗口：点击前 {fg_before:#x} -> 点击后 {fg_after:#x}（悬浮球自己 {self_hwnd:#x}）")
    ok_focus = fg_after == fg_before
    print(("PASS " if ok_focus else "FAIL ") + "点击悬浮球后前台窗口没有变化（焦点没被抢走）")
    if not ok_focus:
        print("      → 文字会贴到悬浮球自己身上，这个功能等于废的")
    ok_all &= ok_focus

    ok_click = len(clicks) == 1
    print(("PASS " if ok_click else "FAIL ") + f"单击触发了 1 次开始/停止（实际 {len(clicks)} 次）")
    ok_all &= ok_click

    # ---------- 2. 拖动只移动，不触发切换 ----------
    pos_before = btn.pos()
    QCursor.setPos(center)
    pump(app, 100)
    user32.mouse_event(LEFT_DOWN, 0, 0, 0, None)
    QCursor.setPos(QPoint(center.x() + 70, center.y() + 40))
    pump(app, 150)
    user32.mouse_event(LEFT_UP, 0, 0, 0, None)
    pump(app, 200)

    moved = btn.pos() != pos_before
    no_extra_click = len(clicks) == 1
    print(f"\n拖动：{pos_before.x()},{pos_before.y()} -> {btn.pos().x()},{btn.pos().y()}")
    print(("PASS " if moved else "FAIL ") + "拖动后位置改变了")
    print(("PASS " if no_extra_click else "FAIL ") + "拖动没有被误判成点击")
    print(("PASS " if len(moves) == 1 else "FAIL ") + f"拖动结束回传了位置（{len(moves)} 次）")
    ok_all &= moved and no_extra_click and len(moves) == 1

    # ---------- 3. 各状态都能正常绘制 ----------
    paint_ok = True
    for st in ("recording", "transcribing", "injecting", "error", "idle"):
        try:
            btn.set_state(st)
            btn.repaint()
            pump(app, 40)
        except Exception as exc:
            print(f"FAIL 状态 {st} 绘制异常：{exc}")
            paint_ok = False
    print(("PASS " if paint_ok else "FAIL ") + "五种状态都能正常绘制")
    ok_all &= paint_ok

    # ---------- 4. 对照组：证明上面"没抢焦点"那条不是蒙对的 ----------
    # 故意去掉 WindowDoesNotAcceptFocus，其它一模一样。它必须把前台抢走，
    # 否则说明前面的 PASS 是假象（比如点击根本没送达到窗口上）。
    from PySide6.QtWidgets import QWidget

    naive = QWidget(None)
    naive.setWindowFlags(
        Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    )
    naive.setAttribute(Qt.WA_TranslucentBackground, True)
    naive.setFixedSize(52, 52)
    naive.move(btn.x(), btn.y() + 100)
    naive.show()
    pump(app, 250)

    QCursor.setPos(naive.geometry().center())
    pump(app, 120)
    fg0 = get_foreground_window()
    click()
    pump(app, 400)
    fg1 = get_foreground_window()
    naive_hwnd = int(naive.winId())
    # 不能断言"前台变成了球自己"：Qt 在窗口被激活时会把激活权转交回进程内
    # 上一个活动窗口（这里就是那个编辑器），所以最终前台常常是别的窗口。
    # 有意义的是"前台被搅动了"——这正是悬浮球必须避免、而上面必须为零的变化。
    disturbed = fg1 != fg0
    print(f"\n对照组（去掉不抢焦点标志）：前台 {fg0:#x} -> {fg1:#x}"
          f"（它自己 {naive_hwnd:#x}，{'就是它自己' if fg1 == naive_hwnd else '被 Qt 转交给了同进程其它窗口'}）")
    print(("PASS " if disturbed else "FAIL ") + "对照组确实搅动了前台 —— 证明上面的测试不是蒙对的")
    ok_all &= disturbed

    naive.close()
    btn.close()
    editor.close()
    print("\n" + ("全部通过" if ok_all else "存在失败项"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
