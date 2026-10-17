"""核心模块自检（不依赖 Qt / 不依赖麦克风）。

覆盖：后处理规则、状态机、热键解析、DPAPI 加解密、**剪贴板无损备份还原**。
最后一项是重点——它直接关系到用户数据会不会被弄丢。
"""
from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import postprocess, win32util as w32  # noqa: E402
from app.config import Config, dpapi_decrypt, dpapi_encrypt  # noqa: E402
from app.hotkey import HotkeyError, parse_hotkey  # noqa: E402
from app.state import State, StateMachine  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def test_postprocess() -> None:
    print("\n== 后处理 ==")
    check("去句首填充词", postprocess.process("嗯，今天天气不错") == "今天天气不错。",
          postprocess.process("嗯，今天天气不错"))
    check("保留正常用法", "好啊" in postprocess.process("好啊，我们走吧"))
    check("去重复赘词", "就是说" not in postprocess.process("就是说这个方案可行"))
    check("合并重复标点", postprocess.process("你好。。。") == "你好。")
    check("补句末句号", postprocess.process("没有标点结尾").endswith("。"))
    check("中文标点归一", postprocess.process("第一点,很重要") == "第一点，很重要。",
          postprocess.process("第一点,很重要"))
    check("空输入", postprocess.process("") == "")
    check("中文字间空格清理", postprocess.process("今天  天气") == "今天天气。")


def test_state() -> None:
    print("\n== 状态机 ==")
    seen = []
    sm = StateMachine(on_change=lambda p, c: seen.append((p.value, c.value)))
    check("IDLE→RECORDING", sm.try_transition(State.RECORDING))
    check("RECORDING→TRANSCRIBING", sm.try_transition(State.TRANSCRIBING))
    check("拒绝非法迁移 TRANSCRIBING→RECORDING", not sm.try_transition(State.RECORDING))
    check("TRANSCRIBING→INJECTING", sm.try_transition(State.INJECTING))
    check("INJECTING→IDLE", sm.try_transition(State.IDLE))
    check("回调次数", len(seen) == 4, str(seen))


def test_hotkey() -> None:
    print("\n== 热键解析 ==")
    check("Ctrl+Alt+Space", parse_hotkey("Ctrl+Alt+Space") == (0x0002 | 0x0001, 0x20))
    check("F9 加修饰键", parse_hotkey("ctrl+F9")[1] == 0x78)
    try:
        parse_hotkey("Space")
        check("无修饰键应报错", False)
    except HotkeyError:
        check("无修饰键应报错", True)
    try:
        parse_hotkey("Ctrl+Nope")
        check("未知键应报错", False)
    except HotkeyError:
        check("未知键应报错", True)


def test_dpapi() -> None:
    print("\n== 密钥加密 ==")
    plain = "LTAI-test-1234567890"
    enc = dpapi_encrypt(plain)
    check("密文不是明文", enc != plain and enc.startswith("enc:"))
    check("解密还原", dpapi_decrypt(enc) == plain)
    check("空值安全", dpapi_encrypt("") == "" and dpapi_decrypt("") == "")


def test_clipboard() -> None:
    print("\n== 剪贴板无损备份（关键）==")
    original = "VoiceType-原始内容-勿删-9527"

    # 先放入纯文本 + 一个自定义格式，模拟真实的多格式剪贴板
    fmt_html = w32.register_clipboard_format("HTML Format")
    check("写入原始文本", w32.set_clipboard_text(original))
    check("原始文本可读", w32.get_clipboard_text() == original)

    snap = w32.ClipboardSnapshot.capture()
    check("快照非空", len(snap.entries) >= 1, snap.summary())
    print(f"         快照内容：{snap.summary()}")
    if snap.skipped:
        print(f"         跳过格式：{snap.skipped}")

    check("写入待注入文本", w32.set_clipboard_text("这是要贴到光标的文字"))
    check("剪贴板已被替换", w32.get_clipboard_text() == "这是要贴到光标的文字")

    check("还原剪贴板", snap.restore())
    check("内容完全还原", w32.get_clipboard_text() == original,
          f"实际={w32.get_clipboard_text()!r}")

    # 二次确认：多格式（含 HTML Format）也能还原
    try:
        html = "<p>rich</p>".encode("utf-8")
        html_h = w32.kernel32.GlobalAlloc(w32.GMEM_MOVEABLE, len(html))
        hp = w32.kernel32.GlobalLock(html_h)
        ctypes.memmove(hp, html, len(html))
        w32.kernel32.GlobalUnlock(html_h)
        w32.user32.OpenClipboard(None)
        w32.user32.EmptyClipboard()
        w32.user32.SetClipboardData(13, _alloc(original))
        w32.user32.SetClipboardData(fmt_html, html_h)
        w32.user32.CloseClipboard()
        snap2 = w32.ClipboardSnapshot.capture()
        n = len(snap2.entries)
        check("多格式快照（>=2 项）", n >= 2, f"实际 {n} 项：{snap2.summary()}")
        w32.set_clipboard_text("覆盖掉")
        snap2.restore()
        check("多格式还原后文本正确", w32.get_clipboard_text() == original)
    except Exception as exc:
        check("多格式还原", False, repr(exc))

    # 无论如何把原始内容还回去
    w32.set_clipboard_text(original)


def _alloc(text: str):
    """必须走 w32.kernel32（已声明 restype），否则 64 位下句柄会被截断。"""
    data = text.encode("utf-16-le") + b"\x00\x00"
    h = w32.kernel32.GlobalAlloc(w32.GMEM_MOVEABLE, len(data))
    p = w32.kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    w32.kernel32.GlobalUnlock(h)
    return h


def test_config() -> None:
    print("\n== 配置 ==")
    cfg = Config()
    check("默认热键", cfg.get("hotkey.binding") == "Ctrl+Alt+Space")
    cfg.set_secret("appkey", "abc")
    check("密钥加密落盘", str(cfg.get("engine.appkey", "")).startswith("enc:"))
    check("密钥读取解密", cfg.secret("appkey") == "abc")
    check("点号设置", (cfg.set("ui.opacity", 0.5) or cfg.get("ui.opacity")) == 0.5)


def main() -> int:
    w32.enable_dpi_awareness()
    for fn in (test_postprocess, test_state, test_hotkey, test_dpapi,
               test_clipboard, test_config):
        try:
            fn()
        except Exception:
            global FAIL
            FAIL += 1
            print(f"  [FAIL] {fn.__name__} 异常：")
            traceback.print_exc()
    print(f"\n结果：通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
