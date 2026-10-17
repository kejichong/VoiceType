"""诊断：打包后的 exe 按下热键时，屏幕上到底发生了什么。

全屏截图存盘（base.png / after.png），并找出"变化像素的外接矩形"，
这样能看出是压根没画、还是画到了别的位置。
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
OUT = ROOT / ".venv" / "diag"
OUT.mkdir(parents=True, exist_ok=True)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]


def tap_hotkey() -> None:
    for vk in (0x11, 0x12, 0x20):
        user32.keybd_event(vk, 0, 0, None)
    for vk in (0x20, 0x12, 0x11):
        user32.keybd_event(vk, 0, 0x0002, None)


def main() -> int:
    subprocess.run(["taskkill", "/F", "/IM", "VoiceType.exe"], capture_output=True)
    time.sleep(0.6)

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    scr = app.primaryScreen()
    print(f"逻辑尺寸 {scr.geometry().width()}x{scr.geometry().height()}  "
          f"物理 {scr.size().width()}x{scr.size().height()}  dpr={scr.devicePixelRatio():g}")

    offset = LOG.stat().st_size if LOG.exists() else 0
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    end = time.monotonic() + 25
    ready = False
    while time.monotonic() < end:
        try:
            with open(LOG, "rb") as f:
                f.seek(offset)
                if "启动完成" in f.read().decode("utf-8", "replace"):
                    ready = True
                    break
        except OSError:
            pass
        time.sleep(0.2)
    print(f"就绪={ready}")
    if not ready:
        proc.kill()
        return 1
    time.sleep(1.6)

    # 把抓屏换成"整个虚拟桌面"，避免区域算错
    geo = scr.geometry()
    base = scr.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height()).toImage()
    base.save(str(OUT / "base.png"))
    print(f"底图 {base.width()}x{base.height()}  中心像素色={base.pixelColor(base.width()//2, base.height()//2).name()}")

    tap_hotkey()
    time.sleep(0.9)
    after = scr.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height()).toImage()
    after.save(str(OUT / "after.png"))

    # 找变化区域的外接矩形
    minx, miny, maxx, maxy, n = 10**9, 10**9, -1, -1, 0
    for yy in range(0, base.height(), 2):
        for xx in range(0, base.width(), 2):
            ca, cb = base.pixelColor(xx, yy), after.pixelColor(xx, yy)
            if (abs(ca.red() - cb.red()) > 12 or abs(ca.green() - cb.green()) > 12
                    or abs(ca.blue() - cb.blue()) > 12):
                n += 1
                minx, miny = min(minx, xx), min(miny, yy)
                maxx, maxy = max(maxx, xx), max(maxy, yy)
    print(f"变化像素 {n} 个；外接矩形 = ({minx},{miny})-({maxx},{maxy})"
          if n else "变化像素 0 个 —— 屏幕上什么都没变")

    time.sleep(1.0)
    tap_hotkey()
    time.sleep(0.5)
    proc.kill()
    print(f"图已存到 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
