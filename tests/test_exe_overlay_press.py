"""对打包后的 exe 做端到端验证：真按热键，真看屏幕。

前面那些测试跑的是源码，用的还是同一个 Python 进程，测不出打包后的行为差异。
这个脚本干的是用户真正会做的事：
  1. 启动 dist\\VoiceType\\VoiceType.exe
  2. 等它就绪（读日志，不靠 sleep 猜）
  3. 抓屏记下"没框"的底图
  4. 用 keybd_event 真按一次 Ctrl+Alt+Space
  5. 轮询屏幕，量出从按键到"框真的出现在屏幕上"的毫秒数
  6. 再按一次收工，确认框消失、桌面复原
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
EXE = ROOT / "dist" / "VoiceType" / "VoiceType.exe"
LOG = Path.home() / "AppData" / "Roaming" / "VoiceType" / "logs" / "app.log"

OVERLAY_W, OVERLAY_H, OFFSET_BOTTOM = 300, 62, 72


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.POINTER(RECT), wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.restype = None

VK_CTRL, VK_ALT, VK_SPACE = 0x11, 0x12, 0x20
KEYUP = 0x0002


def work_area() -> RECT:
    r = RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r


def tap_hotkey() -> None:
    for vk in (VK_CTRL, VK_ALT, VK_SPACE):
        user32.keybd_event(vk, 0, 0, None)
    for vk in (VK_SPACE, VK_ALT, VK_CTRL):
        user32.keybd_event(vk, 0, KEYUP, None)


def kill_existing() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "VoiceType.exe"],
                   capture_output=True, shell=False)


def log_tail(n: int = 6) -> str:
    """日志被进程占用，必须以共享读方式打开。"""
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def wait_ready(offset: int, timeout: float = 25.0) -> bool:
    """等本次启动写出"启动完成"。

    必须从 offset 往后读——日志里躺着历史运行的"启动完成"，
    直接 tail 搜会立刻误判成"已就绪"，然后测的就是启动中的窗口。
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with open(LOG, "rb") as f:      # 进程占用，必须共享读
                f.seek(offset)
                fresh = f.read().decode("utf-8", errors="replace")
        except OSError:
            fresh = ""
        if "启动完成" in fresh:
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    if not EXE.exists():
        print("exe 不存在，先跑 build.ps1")
        return 1

    kill_existing()
    time.sleep(0.6)

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    scr = app.primaryScreen()

    wa = work_area()
    # 注意：SPI_GETWORKAREA 给的是物理像素，而 Qt 的窗口坐标是逻辑像素
    # （这台机器 2160x1440 物理 / 150% 缩放 = 1440x960 逻辑）。
    # 混用会导致截屏截到完全不相干的区域，测出来永远是"没出现"。
    # 所以区域一律用 Qt 的 availableGeometry 来算。
    geo = scr.availableGeometry()
    x = geo.x() + (geo.width() - OVERLAY_W) // 2
    y = geo.y() + geo.height() - OVERLAY_H - OFFSET_BOTTOM
    print(f"逻辑工作区 {geo.width()}x{geo.height()}（物理 {wa.right - wa.left}x{wa.bottom - wa.top}，"
          f"缩放 {scr.devicePixelRatio():g}x），悬浮窗应在 ({x}, {y})")

    log_offset = LOG.stat().st_size if LOG.exists() else 0
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    if not wait_ready(log_offset):
        print("启动超时，日志尾部：")
        print(log_tail(15))
        proc.kill()
        return 1
    print("程序已就绪")

    def full_screen():
        g = scr.geometry()
        return scr.grabWindow(0, g.x(), g.y(), g.width(), g.height()).toImage()

    # 一律"全屏抓 + 手动裁"：QScreen.grabWindow 传子区域时，x/y 与 w/h 的
    # 缩放语义容易踩坑（混用逻辑/物理像素会截到旁边去，差分数永远是 0）。
    # 全屏抓取返回的是物理像素图，自己按 dpr 换算裁剪就没歧义了。
    scale = scr.devicePixelRatio()

    def shot():
        img = full_screen()
        return img.copy(int(x * scale), int(y * scale),
                        int(OVERLAY_W * scale), int(OVERLAY_H * scale))

    def mean_luma(img) -> float:
        tot = cnt = 0
        for yy in range(0, img.height(), 3):
            for xx in range(0, img.width(), 3):
                c = img.pixelColor(xx, yy)
                tot += (c.red() + c.green() + c.blue()) / 3
                cnt += 1
        return tot / max(cnt, 1)

    def changed(a, b, thr: int = 12) -> int:
        if a.size() != b.size():
            return -1
        n = 0
        for yy in range(0, a.height(), 2):
            for xx in range(0, a.width(), 2):
                ca, cb = a.pixelColor(xx, yy), b.pixelColor(xx, yy)
                if (abs(ca.red() - cb.red()) > thr
                        or abs(ca.green() - cb.green()) > thr
                        or abs(ca.blue() - cb.blue()) > thr):
                    n += 1
        return n

    def wait_clear(timeout: float = 10.0):
        """等悬浮窗区域回到桌面本色（既没有卡片，也没有任何提示条）。"""
        end = time.monotonic() + timeout
        while True:
            img = shot()
            if mean_luma(img) > 120:
                return img, True
            if time.monotonic() > end:
                return img, False
            time.sleep(0.2)

    # 启动时会显示 3.2 秒的"已就绪 · <热键>"提示，和识别框是同一块区域。
    # 不等它收起就取底图，底图本身就是一个深色卡片，按键后的差分自然是 0,
    # 这会把"其实是好的"误判成"框没出现"。所以等到该区域变亮为止。
    base, cleared = wait_clear(11)
    if not cleared:
        print(f"FAIL 启动提示 11 秒内没有收起（区域亮度 {mean_luma(base):.0f}）")
        proc.kill()
        return 1

    sampled = (base.width() // 2) * (base.height() // 2)
    time.sleep(0.15)
    idle_diff = changed(base, shot())
    ok_idle = idle_diff < sampled * 0.06
    print(f"\n[就绪空闲] 取景 {base.width()}x{base.height()}，"
          f"亮度 {mean_luma(base):.0f}，与底图差异 {idle_diff} 像素")
    print(("PASS " if ok_idle else "FAIL ") + "空闲时屏幕上没有常驻窗口残影")

    print("\n>>> 按下 Ctrl+Alt+Space")
    t0 = time.monotonic()
    tap_hotkey()

    visible_ms = None
    last = base
    while time.monotonic() - t0 < 1.2:
        last = shot()
        if changed(base, last) > sampled * 0.35:
            visible_ms = (time.monotonic() - t0) * 1000
            break
        time.sleep(0.008)

    if visible_ms is None:
        print("FAIL 按下去 1.2 秒内屏幕上没有出现识别框")
        print(f"     取景区域亮度 {mean_luma(base):.0f} -> {mean_luma(last):.0f}")
        last.save(str(ROOT / ".venv" / "diag" / "press_fail.png"))
        print("日志尾部：")
        print(log_tail(10))
        proc.kill()
        return 1

    print(f"识别框出现在屏幕上，耗时 {visible_ms:.0f} ms")
    ok_fast = visible_ms < 200
    print(("PASS " if ok_fast else "FAIL ") + f"按键到可见 {visible_ms:.0f}ms < 200ms（含进程外注入开销）")

    # 再按一次结束这次空录音
    time.sleep(0.5)
    tap_hotkey()
    # 空录音结束后会弹 2.6 秒的"这次没听到声音"错误提示，用的还是同一块区域。
    # 不等它自己收起就判定"桌面复原"，数到的其实是这条提示，不是框的残影。
    deadline = time.monotonic() + 6
    residue_img = shot()
    while time.monotonic() < deadline:
        residue_img = shot()
        if mean_luma(residue_img) > 120:
            break
        time.sleep(0.2)
    residue = changed(base, residue_img)
    ok_clean = residue < sampled * 0.06
    print(f"\n[收起后] 区域亮度 {mean_luma(residue_img):.0f}，与底图差异 {residue} 像素")
    print(("PASS " if ok_clean else "FAIL ") + "框已消失，桌面复原")

    print("\n日志尾部：")
    print(log_tail(8))

    proc.kill()
    time.sleep(0.3)
    ok = ok_idle and ok_fast and ok_clean
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
