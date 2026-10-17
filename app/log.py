"""日志：滚动写入 %APPDATA%\\VoiceType\\logs\\app.log。

这类工具最典型的故障是「偶尔贴不进去」，没有日志几乎无法定位，
所以状态迁移、目标窗口、注入结果都要记。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import config_dir

_LOGGER_NAME = "voicetype"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    log_dir = config_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    except OSError:
        pass
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
