"""音频采集冒烟测试：验证麦克风、预录环形缓冲、电平。

结果写文件，避免控制台编码干扰。
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / ".venv" / "audio.txt"
lines: list[str] = []


def log(msg: str) -> None:
    lines.append(msg)


def main() -> int:
    try:
        from app.audio import Recorder

        devs = Recorder.list_devices()
        log(f"输入设备数: {len(devs)}")
        for idx, name in devs[:6]:
            log(f"  [{idx}] {name}")

        chunks: list[bytes] = []
        levels: list[float] = []
        rec = Recorder(on_chunk=chunks.append, on_level=levels.append)
        try:
            rec.open()
        except Exception as exc:
            log(f"打开麦克风失败: {exc!r}")
            log("RESULT: NO_DEVICE")
            OUT.write_text("\n".join(lines), encoding="utf-8")
            return 2

        log("麦克风已打开")
        # 先静置 0.7 秒让预录环形缓冲填满
        time.sleep(0.7)
        rec.start_session()
        preroll = len(chunks)
        log(f"按下快捷键瞬间吐出预录块数: {preroll}（预期 5 块 ≈ 0.5 秒）")

        time.sleep(1.0)
        rec.end_session()
        time.sleep(0.15)
        rec.close()

        total = sum(len(c) for c in chunks)
        seconds = total / 32000.0
        log(f"会话总字节: {total}（≈{seconds:.2f} 秒音频）")
        log(f"回调块数: {len(chunks)}，单块字节: {len(chunks[0]) if chunks else 0}")
        log(f"电平样本数: {len(levels)}")
        if levels:
            log(f"平均电平: {sum(levels) / len(levels):.5f}  最大: {max(levels):.5f}")
        log(f"采样率/声道: 16000 / 单声道 / 16bit = {32000} 字节每秒")
        log("RESULT: OK")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 0
    except Exception:
        log("RESULT: FAIL")
        log(traceback.format_exc())
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())
