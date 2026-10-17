"""会话状态机。

快捷键是「切换」语义，用户双击/误触/上一段没处理完又按一次都会发生。
所有状态迁移必须经过这里，非法迁移直接拒绝——这是避免
「一次按键贴出两段话」这类竞态的唯一办法。
"""
from __future__ import annotations

import threading
from enum import Enum
from typing import Callable


class State(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    INJECTING = "injecting"
    ERROR = "error"


_ALLOWED: dict[State, set[State]] = {
    State.IDLE: {State.RECORDING},
    State.RECORDING: {State.TRANSCRIBING, State.IDLE, State.ERROR},
    State.TRANSCRIBING: {State.INJECTING, State.IDLE, State.ERROR},
    State.INJECTING: {State.IDLE, State.ERROR},
    State.ERROR: {State.IDLE},
}


class StateMachine:
    def __init__(self, on_change: Callable[[State, State], None] | None = None) -> None:
        self._state = State.IDLE
        self._on_change = on_change
        self._lock = threading.RLock()

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def can(self, target: State) -> bool:
        with self._lock:
            return target in _ALLOWED.get(self._state, set())

    def try_transition(self, target: State) -> bool:
        with self._lock:
            if target not in _ALLOWED.get(self._state, set()):
                return False
            prev, self._state = self._state, target
        if self._on_change:
            self._on_change(prev, target)
        return True

    def force(self, target: State) -> None:
        """异常恢复用：无视规则重置状态。"""
        with self._lock:
            prev, self._state = self._state, target
        if self._on_change:
            self._on_change(prev, target)
