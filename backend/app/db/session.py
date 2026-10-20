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
    """建表（幂等），并为已有表补充新增的列。"""
    engine = init_engine(cfg)
    import_models()
    Base.metadata.create_all(bind=engine)
    _migrate_missing_columns(engine)
    _backfill_kb_visibility(engine)
    ensure_default_roles(engine)
    ensure_all_users_have_default_role(engine)
    logger.info("数据库表初始化完成：%s", ", ".join(sorted(Base.metadata.tables)))


def _backfill_kb_visibility(engine) -> None:
    """升级兼容：把 visibility 为 NULL / 空串的存量知识库回填为 private。

    SQLAlchemy 的列级 default 只在 ORM INSERT 时生效，ALTER TABLE ADD COLUMN
    不会给历史行赋值；这里显式 UPDATE，保证旧库升级后语义与方案一致。
    """
    with engine.begin() as connection:
        result = connection.execute(
            text(
                "UPDATE knowledge_bases SET visibility = 'private' "
                "WHERE visibility IS NULL OR visibility = ''"
            )
        )
    if result.rowcount:
        logger.info("回填存量知识库可见范围为 private：%s 条", result.rowcount)


# 内置角色定义（启动时幂等插入 / 升级时补齐）
_DEFAULT_ROLES: tuple[tuple[str, str, str, bool], ...] = (
    ("admin", "管理员", "可访问与管理系统全部资源，包含角色与知识库授权管理", True),
    ("staff", "业务人员", "可访问被授权的知识库，进行检索与日常问答", True),
    ("viewer", "访客", "默认角色：仅可访问公开（visibility=all）知识库与被授权的私有库", True),
)


def ensure_default_roles(engine) -> None:
    """幂等插入三个系统内置角色，重复执行不会报错。"""
    from sqlalchemy import select

    from .models import Role

    with engine.begin() as connection:
        existing_codes = set(
            connection.execute(select(Role.code)).scalars().all()
        )
        for code, name, description, is_system in _DEFAULT_ROLES:
            if code in existing_codes:
                # 已存在：仅刷新 name/description（code 不可变）
                connection.execute(
                    Role.__table__.update()
                    .where(Role.code == code)
                    .values(name=name, description=description)
                )
                continue
            connection.execute(
                Role.__table__.insert().values(
                    code=code, name=name, description=description, is_system=is_system
                )
            )


def ensure_all_users_have_default_role(engine) -> None:
    """为所有没有角色的存量用户补发 viewer 默认角色（升级兼容）。"""
    from sqlalchemy import select

    from .models import Role, User, UserRole

    with session_scope() as session:
        viewer = session.scalar(select(Role).where(Role.code == "viewer"))
        if viewer is None:
            return  # 上面 ensure_default_roles 已保证，但为兼容 race 兜底

        existing_pairs = {
            (row.user_id, row.role_id)
            for row in session.execute(select(UserRole.user_id, UserRole.role_id)).all()
        }
        all_users = session.scalars(select(User.id)).all()
        missing = [uid for uid in all_users if (uid, viewer.id) not in existing_pairs]
        if not missing:
            return

        for uid in missing:
            session.add(UserRole(user_id=uid, role_id=viewer.id))
        session.commit()
        logger.info("为 %s 个存量用户补发默认角色 viewer", len(missing))


def _existing_columns(connection, table_name: str, is_sqlite: bool) -> set[str] | None:
    """查询表中已存在的列名；表不存在时返回 None。"""
    if is_sqlite:
        rows = connection.execute(text(f"PRAGMA table_info(`{table_name}`)")).all()
        if not rows:
            return None
        return {str(row[1]) for row in rows}
    rows = connection.execute(
        text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name"
        ),
        {"table_name": table_name},
    ).all()
    if not rows:
        return None
    return {str(row[0]) for row in rows}


def _column_ddl(column, is_sqlite: bool) -> str:
    """把 ORM 列编译为 ALTER TABLE ADD COLUMN 的 DDL 片段（仅用于补列）。"""
    from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, JSON, String, Text

    col_type = column.type
    if isinstance(col_type, String):
        ddl_type = f"VARCHAR({col_type.length or 255})"
    elif isinstance(col_type, Text):
        ddl_type = "TEXT"
    elif isinstance(col_type, BigInteger):
        ddl_type = "BIGINT"
    elif isinstance(col_type, Integer):
        ddl_type = "INT"
    elif isinstance(col_type, Boolean):
        ddl_type = "INTEGER" if is_sqlite else "TINYINT(1)"
    elif isinstance(col_type, Float):
        ddl_type = "REAL" if is_sqlite else "DOUBLE"
    elif isinstance(col_type, DateTime):
        ddl_type = "DATETIME"
    elif isinstance(col_type, JSON):
        ddl_type = "TEXT" if is_sqlite else "JSON"
    else:  # pragma: no cover - 未知类型按文本兜底
        ddl_type = "TEXT"
    nullable = "NULL" if column.nullable else "NOT NULL"
    # 带上 server_default，补列时历史行与新行都有正确的默认值
    # （列级 default 只在 ORM INSERT 时生效，DDL 默认值需要单独声明）
    default_clause = ""
    server_default = getattr(column, "server_default", None)
    default_arg = getattr(server_default, "arg", None)
    if default_arg:
        default_clause = f" DEFAULT {default_arg}"
    return f"ADD COLUMN `{column.name}` {ddl_type} {nullable}{default_clause}"


def _migrate_missing_columns(engine) -> None:
    """为已有表补充 ORM 中新增的列。

    create_all 只会创建缺失的表，不会给已存在的表加列；
    版本升级新增字段（如 chat_messages.feedback）时在这里自动补列，无需手工执行 SQL。
    补列失败仅告警，不阻塞启动（可在日志中定位）。
    """
    is_sqlite = engine.dialect.name == "sqlite"
    added: list[str] = []
    try:
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                existing = _existing_columns(connection, table.name, is_sqlite)
                if existing is None:
                    continue  # 表不存在（create_all 刚创建，列必然齐全）
                for column in table.columns:
                    if column.name in existing or column.primary_key:
                        continue
                    statement = f"ALTER TABLE `{table.name}` {_column_ddl(column, is_sqlite)}"
                    logger.info("补充缺失的数据表列：%s.%s", table.name, column.name)
                    connection.execute(text(statement))
                    added.append(f"{table.name}.{column.name}")
    except Exception as exc:  # noqa: BLE001 - 补列失败不阻塞启动
        logger.warning("自动补充数据表列失败（可忽略后重试或手工 ALTER TABLE）：%s", exc)
        return
    if added:
        logger.info("已自动补充缺失列：%s", ", ".join(added))


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
