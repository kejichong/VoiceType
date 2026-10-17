"""音频采集：16kHz / 单声道 / 16bit，带预录环形缓冲。

预录的意义：麦克风数据流常开，始终保留最近 0.5 秒。
用户按快捷键的瞬间把预录一起送出去，第一个字就不会被吃掉。
"""
from __future__ import annotations

import collections
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK_MS = 100
BLOCK_FRAMES = SAMPLE_RATE * BLOCK_MS // 1000  # 1600 帧 = 3200 字节
MAX_SESSION_SEC = 180


class AudioError(Exception):
    pass


class Recorder:
    def __init__(
        self,
        on_chunk: Callable[[bytes], None],
        on_level: Callable[[float], None] | None = None,
        sample_rate: int = SAMPLE_RATE,
        preroll_sec: float = 0.5,
    ) -> None:
        self._on_chunk = on_chunk
        self._on_level = on_level
        self._sr = sample_rate
        self._preroll_len = max(1, int(preroll_sec * 1000 / BLOCK_MS))
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=self._preroll_len)
        self._stream: sd.InputStream | None = None
        self._active = threading.Event()
        self._lock = threading.Lock()
        self._sent_bytes = 0
        self._max_bytes = MAX_SESSION_SEC * sample_rate * 2
        self._device_index: int | None = None

    # ---------- 生命周期 ----------
    def open(self, device: int | None = None) -> None:
        if self._stream is not None and self._device_index == device:
            return
        self.close()
        try:
            self._stream = sd.InputStream(
                samplerate=self._sr,
                blocksize=BLOCK_FRAMES,
                channels=1,
                dtype="int16",
                device=device,
                callback=self._callback,
            )
            self._stream.start()
            self._device_index = device
        except Exception as exc:  # 无麦克风 / 被独占 / 权限被拒
            self._stream = None
            raise AudioError(f"麦克风打开失败：{exc}") from exc

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self._device_index = None

    # ---------- 采集回调（PortAudio 线程，必须轻量）----------
    def _callback(self, indata, frames, time_info, status) -> None:
        pcm = indata.tobytes()
        if self._on_level is not None:
            try:
                self._on_level(float(np.abs(indata).mean()) / 32768.0)
            except Exception:
                pass
        if self._active.is_set():
            with self._lock:
                if self._sent_bytes >= self._max_bytes:
                    self._active.clear()
                    return
                self._sent_bytes += len(pcm)
            try:
                self._on_chunk(pcm)
            except Exception:
                pass
        else:
            self._preroll.append(pcm)

    # ---------- 会话 ----------
    def start_session(self) -> None:
        with self._lock:
            pre = list(self._preroll)
            self._preroll.clear()
            self._sent_bytes = 0
            self._active.set()
        for chunk in pre:
            try:
                self._on_chunk(chunk)
            except Exception:
                pass

    def end_session(self) -> None:
        self._active.clear()

    @property
    def active(self) -> bool:
        return self._active.is_set()

    @staticmethod
    def list_devices() -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0:
                    out.append((i, dev.get("name", f"设备 {i}")))
        except Exception:
            pass
        return out
