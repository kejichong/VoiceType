"""识别引擎抽象。

设计要点：start/send/finish 三件事分离，且 start 不阻塞。
按下快捷键时必须立刻能开始说话，所以连接过程放在后台线程，
音频先进队列，连上后按序补发——这决定了「说第一句时会不会丢字」。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class EngineError(Exception):
    pass


class AsrEngine(ABC):
    name = "base"

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_partial = on_partial
        self._on_error = on_error

    @abstractmethod
    def start(self) -> None:
        """准备识别（非阻塞）。"""

    @abstractmethod
    def send(self, pcm: bytes) -> None:
        """送一段 16bit/16kHz/单声道 PCM。"""

    @abstractmethod
    def finish(self) -> str:
        """结束并返回完整文本（阻塞，带超时）。"""

    @abstractmethod
    def cancel(self) -> None:
        """中断，丢弃结果。"""

    def _emit_partial(self, text: str) -> None:
        if self._on_partial:
            try:
                self._on_partial(text)
            except Exception:
                pass

    def _emit_error(self, msg: str) -> None:
        if self._on_error:
            try:
                self._on_error(msg)
            except Exception:
                pass
