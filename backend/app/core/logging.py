"""日志模块：同时输出到控制台与文件（按天滚动）。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_CONFIGURED = False


def setup_logging(log_dir: str | Path = "logs", level: str = "INFO", app_name: str = "rag_qa") -> logging.Logger:
    """初始化日志：控制台 + app.log（按天滚动）+ error.log（错误单独留存）。"""
    global _CONFIGURED

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    log_level = getattr(logging, str(level).upper(), logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # 控制台
    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(log_level)
    root.addHandler(console)

    # 全量日志文件
    file_handler = TimedRotatingFileHandler(
        filename=log_path / f"{app_name}.log",
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    root.addHandler(file_handler)

    # 错误日志文件
    error_handler = RotatingFileHandler(
        filename=log_path / f"{app_name}_error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    root.addHandler(error_handler)

    root.setLevel(log_level)

    # 让 uvicorn 的日志复用同一套 handler，避免重复输出
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # 降低第三方库噪音
    for noisy in ("pymilvus", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    logger = logging.getLogger(app_name)
    logger.info("日志系统初始化完成，日志目录：%s，级别：%s", log_path.resolve(), level)
    return logger


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器。"""
    return logging.getLogger(name)


def is_configured() -> bool:
    """是否已初始化日志。"""
    return _CONFIGURED
