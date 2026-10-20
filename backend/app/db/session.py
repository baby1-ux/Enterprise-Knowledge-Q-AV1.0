"""数据库连接与会话管理（MySQL 生产 / SQLite 测试）。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import Settings, settings as current_settings
from .base import Base

logger = logging.getLogger("rag.db")

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def ensure_database(cfg: Settings) -> None:
    """MySQL 场景下自动创建数据库（不存在时）。"""
    if not cfg.database_url.startswith("mysql"):
        return
    try:  # pragma: no cover - 依赖真实 MySQL，测试环境走 SQLite
        import pymysql

        connection = pymysql.connect(
            host=cfg.mysql.host,
            port=cfg.mysql.port,
            user=cfg.mysql.user,
            password=cfg.mysql.password,
            charset=cfg.mysql.charset,
            connect_timeout=5,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{cfg.mysql.database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            connection.commit()
            logger.info("已确认数据库存在：%s", cfg.mysql.database)
        finally:
            connection.close()
    except Exception as exc:  # pragma: no cover
        logger.warning("自动创建数据库失败（请检查 MySQL 是否启动）：%s", exc)


def build_engine(cfg: Settings) -> Engine:
    """根据配置构建数据库引擎。"""
    url = cfg.database_url
    kwargs: dict = {"echo": cfg.mysql.echo, "future": True}

    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        logger.info("使用 SQLite 数据库：%s", url)
    else:
        ensure_database(cfg)
        kwargs.update(
            pool_pre_ping=cfg.mysql.pool_pre_ping,
            pool_size=cfg.mysql.pool_size,
            max_overflow=cfg.mysql.max_overflow,
            pool_recycle=3600,
        )
        logger.info("使用 MySQL 数据库：%s:%s/%s", cfg.mysql.host, cfg.mysql.port, cfg.mysql.database)

    return create_engine(url, **kwargs)


def init_engine(cfg: Settings | None = None, force: bool = False) -> Engine:
    """初始化全局引擎与会话工厂。"""
    global _engine, _session_factory
    if _engine is not None and not force:
        return _engine
    cfg = cfg or current_settings()
    _engine = build_engine(cfg)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    """获取引擎（惰性初始化）。"""
    if _engine is None:
        return init_engine()
    return _engine  # type: ignore[return-value]


def get_session_factory() -> sessionmaker:
    """获取会话工厂。"""
    if _session_factory is None:
        init_engine()
    return _session_factory  # type: ignore[return-value]


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文：自动提交/回滚/关闭。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级数据库会话。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db(cfg: Settings | None = None) -> None:
    """建表（幂等）。"""
    engine = init_engine(cfg)
    import_models()
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表初始化完成：%s", ", ".join(sorted(Base.metadata.tables)))


def import_models() -> None:
    """确保 ORM 模型已注册到 Base.metadata。"""
    from . import models  # noqa: F401


def healthcheck(cfg: Settings | None = None) -> str:
    """数据库连通性检查，返回 ok / error。"""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # pragma: no cover
        logger.error("数据库健康检查失败：%s", exc)
        return "error"


def dispose_engine() -> None:
    """释放引擎（测试/关闭时使用）。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
