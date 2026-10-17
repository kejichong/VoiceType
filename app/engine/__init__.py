"""引擎工厂：把配置翻译成具体引擎实例。"""
from __future__ import annotations

from ..config import Config
from .base import AsrEngine, EngineError
from .mock import MockEngine


def create_engine(cfg: Config, on_partial=None, on_error=None) -> AsrEngine:
    kind = str(cfg.get("engine.type", "aliyun")).lower()

    if kind == "mock":
        return MockEngine(on_partial=on_partial, on_error=on_error)

    if kind == "aliyun":
        from .aliyun import AliyunEngine

        missing = [k for k in ("appkey", "access_key_id", "access_key_secret") if not cfg.secret(k)]
        if missing:
            raise EngineError(
                "阿里云密钥未配置：" + "、".join(missing) + "。请在设置里填写后重试。"
            )
        return AliyunEngine(
            appkey=cfg.secret("appkey"),
            ak_id=cfg.secret("access_key_id"),
            ak_secret=cfg.secret("access_key_secret"),
            region=str(cfg.get("engine.region", "cn-shanghai")),
            vocabulary_id=str(cfg.get("engine.vocabulary_id", "") or ""),
            sample_rate=int(cfg.get("engine.sample_rate", 16000)),
            enable_punctuation=bool(cfg.get("engine.enable_punctuation", True)),
            enable_itn=bool(cfg.get("engine.enable_itn", True)),
            on_partial=on_partial,
            on_error=on_error,
        )

    raise EngineError(f"未知的引擎类型：{kind}")


__all__ = ["AsrEngine", "EngineError", "MockEngine", "create_engine"]
