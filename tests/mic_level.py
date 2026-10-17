"""麦克风电平诊断：录一段环境底噪 + 一段说话，算出信噪比并给出结论。

假引擎报的"电平"是整段平均绝对值（含停顿），单独看 0.03 无法判断
是"说话太小声"还是"环境噪声大"。这个脚本把两者分开量。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

OUT = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序\.venv\mic_level.txt")
SR = 16000
lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    lines.append(msg)


def record(seconds: float, label: str) -> np.ndarray:
    log(f"  [{label}] 录音 {seconds:.1f} 秒…")
    data = sd.rec(int(SR * seconds), samplerate=SR, channels=1, dtype="int16")
    sd.wait()
    return data.reshape(-1).astype(np.float64) / 32768.0


def stats(x: np.ndarray) -> dict:
    if x.size == 0:
        return {"mean_abs": 0.0, "rms": 0.0, "peak": 0.0, "active": 0.0}
    frame = int(SR * 0.02)  # 20ms 一帧
    n = x.size // frame
    frames = x[: n * frame].reshape(n, frame)
    frame_abs = np.abs(frames).mean(axis=1)
    # 有声帧：超过 -40dBFS（0.01）视为有声音
    active = float((frame_abs > 0.01).mean())
    return {
        "mean_abs": float(np.abs(x).mean()),
        "rms": float(np.sqrt((x ** 2).mean())),
        "peak": float(np.abs(x).max()),
        "active": active,
    }


def db(v: float) -> float:
    return 20 * np.log10(max(v, 1e-6))


def main() -> int:
    noise_only = "--noise-only" in sys.argv
    devs = sd.query_devices()
    log("=== 输入设备 ===")
    for i, d in enumerate(devs):
        if d["max_input_channels"] > 0:
            mark = ""
            try:
                if i == sd.default.device[0]:
                    mark = "  <== 当前默认"
            except Exception:
                pass
            log(f"  [{i}] {d['name']}  ch={d['max_input_channels']} "
                f"@{int(d['default_samplerate'])}{mark}")

    try:
        cur = sd.query_devices(kind="input")
        log(f"\n默认输入设备: {cur['name']}")
    except Exception as exc:
        log(f"默认输入设备查询失败: {exc}")

    log("\n=== 第 1 段：保持安静 2.5 秒（测底噪）===")
    time.sleep(1.0)
    quiet = record(2.5, "底噪")
    q = stats(quiet)

    if noise_only:
        log("\n=== 底噪结果（未测说话段）===")
        log(f"底噪  平均绝对值={q['mean_abs']:.4f} ({db(q['mean_abs']):.1f} dBFS)  "
            f"峰值={q['peak']:.4f} ({db(q['peak']):.1f} dBFS)")
        log(f"有声帧占比={q['active'] * 100:.1f}%")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 0

    log("\n=== 第 2 段：请用平时说话的音量念任意一段话（4 秒）===")
    time.sleep(1.0)
    voice = record(4.0, "说话")
    v = stats(voice)

    log("\n=== 结果 ===")
    log(f"底噪  平均绝对值={q['mean_abs']:.4f} ({db(q['mean_abs']):.1f} dBFS)  "
        f"峰值={q['peak']:.4f} ({db(q['peak']):.1f} dBFS)")
    log(f"说话  平均绝对值={v['mean_abs']:.4f} ({db(v['mean_abs']):.1f} dBFS)  "
        f"峰值={v['peak']:.4f} ({db(v['peak']):.1f} dBFS)")
    log(f"有声帧占比={v['active'] * 100:.1f}%")

    snr = db(v["mean_abs"]) - db(q["mean_abs"])
    log(f"估算信噪比 ≈ {snr:.1f} dB")

    log("\n=== 判断 ===")
    verdict = []
    if v["peak"] > 0.99:
        verdict.append("峰值已贴满量程，会削波失真 → 把麦克风音量调低一档")
    if v["mean_abs"] < 0.02:
        verdict.append("说话电平偏低（<0.02）→ 靠近麦克风或提高输入音量，"
                       "阿里云识别对低电平较敏感")
    elif v["mean_abs"] < 0.05:
        verdict.append("说话电平中等偏低（0.02~0.05）→ 可用，但贴近麦克风会更稳")
    else:
        verdict.append("说话电平正常（>0.05）")
    if snr < 12:
        verdict.append("信噪比不足 12dB → 环境噪声偏大，换安静环境或换指向性麦克风")
    if v["active"] < 0.25:
        verdict.append("有声帧太少 → 录音里大部分是静音，注意按完键要马上开口")
    for s in verdict:
        log("  - " + s)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
