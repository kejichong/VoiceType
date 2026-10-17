"""离线假引擎：不需要任何密钥，用于验证「录音→识别→贴字」整条链路。

它把收到的音频按静音/有声分段，返回写死的句子，
用来单独测试热键、采集、注入、悬浮窗是否正常。
"""
from __future__ import annotations

import threading
import time

import numpy as np

from .base import AsrEngine

_SAMPLES = [
    "这是一段用于联调的测试文字。",
    "链路已经打通，热键、录音、注入都正常工作。",
    "如果这段话出现在你的光标处，说明整个流程没问题。",
]


class MockEngine(AsrEngine):
    name = "离线假引擎（联调用）"

    def __init__(self, on_partial=None, on_error=None, delay: float = 0.35) -> None:
        super().__init__(on_partial, on_error)
        self._delay = delay
        self._chunks: list[bytes] = []
        self._abort = threading.Event()
        self._index = 0

    def start(self) -> None:
        self._chunks.clear()
        self._abort.clear()

    def send(self, pcm: bytes) -> None:
        if not self._abort.is_set():
            self._chunks.append(pcm)
            if len(self._chunks) % 6 == 0:
                partial = "（正在听……）"
                self._emit_partial(partial)

    def finish(self) -> str:
        time.sleep(self._delay)
        audio_len = sum(len(c) for c in self._chunks)
        if audio_len < 16000:  # 不足 0.5 秒，当作误触
            return ""
        try:
            peak = np.frombuffer(b"".join(self._chunks), dtype=np.int16)
            loud = float(np.abs(peak).mean()) / 32768.0
        except Exception:
            loud = 0.0
        text = _SAMPLES[self._index % len(_SAMPLES)]
        self._index += 1
        return f"{text}（电平 {loud:.3f}，音频 {audio_len / 32000:.1f} 秒）"

    def cancel(self) -> None:
        self._abort.set()
        self._chunks.clear()
