"""录 12 秒麦克风，用修好的引擎跑一遍，验证文本字段解析。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from app.config import Config  # noqa: E402
from app.engine.aliyun import AliyunEngine  # noqa: E402

OUT = PROJ / ".venv" / "replay.txt"
SR = 16000
SECS = 12.0
lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    lines.append(msg)


def main() -> int:
    cfg = Config.load()
    log(f"开始录音 {SECS:.0f} 秒，请正常说话…")
    data = sd.rec(int(SR * SECS), samplerate=SR, channels=1, dtype="int16")
    sd.wait()
    pcm = data.reshape(-1)
    peak = float(np.abs(pcm).max()) / 32768.0
    log(f"录完：峰值电平 {peak:.3f}，字节 {pcm.nbytes}")

    partials: list[str] = []
    eng = AliyunEngine(
        appkey=cfg.secret("appkey"),
        ak_id=cfg.secret("access_key_id"),
        ak_secret=cfg.secret("access_key_secret"),
        region=str(cfg.get("engine.region", "cn-shanghai")),
        on_partial=lambda t: partials.append(t),
        on_error=lambda m: log(f"[引擎错误] {m}"),
    )
    eng.start()

    raw = pcm.tobytes()
    step = 3200
    for i in range(0, len(raw), step):
        eng.send(raw[i:i + step])
        time.sleep(0.1)

    try:
        text = eng.finish()
    except Exception as exc:
        log(f"finish 失败：{exc}")
        text = ""

    log(f"\n最终文本 = {text!r}")
    log(f"统计 = {eng.last_stats}")
    log(f"中间结果回调 {len(partials)} 次")
    for i, p in enumerate(partials[-6:]):
        log(f"  partial[{i}] = {p!r}")

    verdict = "OK 有文字" if text.strip() else "FAIL 仍然为空"
    log(f"\nRESULT: {verdict}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    return 0 if text.strip() else 1


if __name__ == "__main__":
    sys.exit(main())
