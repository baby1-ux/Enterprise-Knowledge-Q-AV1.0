"""数据库自动补列迁移测试：init_db 为已有表补充 ORM 新增的列。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.core.config import Settings, clear_settings_override, override_settings
from app.db.session import dispose_engine, get_engine, init_db, init_engine

# 旧版本 chat_messages 表结构（缺少 feedback 列）
_LEGACY_CHAT_MESSAGES_DDL = """
CREATE TABLE chat_messages (
    id INTEGER NOT NULL PRIMARY KEY,
    session_id INTEGER NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    citations JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _column_names(table_name: str) -> set[str]:
    """读取 SQLite 表的列名集合。"""
    with get_engine().connect() as connection:
        rows = connection.execute(text(f"PRAGMA table_info({table_name})")).all()
    return {str(row[1]) for row in rows}


def test_init_db_adds_missing_columns(tmp_path: Path) -> None:
    """旧库缺少 feedback 列时，init_db 自动补列且不破坏已有数据。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    db_file = tmp_path / "legacy.db"
    cfg.mysql.url_override = f"sqlite:///{db_file.as_posix()}"

    # 1. 构造旧版本数据库：只有 chat_messages 一张表，且缺少 feedback 列
    from sqlalchemy import create_engine

    legacy_engine = create_engine(cfg.mysql.url_override)
    with legacy_engine.begin() as connection:
        connection.execute(text(_LEGACY_CHAT_MESSAGES_DDL))
        connection.execute(
            text(
                "INSERT INTO chat_messages (session_id, role, content) "
                "VALUES (1, 'assistant', '旧数据：保修期为一年')"
            )
        )
    legacy_engine.dispose()

    # 2. 运行初始化：create_all 补齐其它表 + 自动补列
    override_settings(cfg)
    try:
        init_engine(cfg, force=True)
        init_db(cfg)

        columns = _column_names("chat_messages")
        assert "feedback" in columns
        assert {"id", "session_id", "role", "content", "citations", "created_at"} <= columns

        # 3. 已有数据不受影响
        with get_engine().connect() as connection:
            rows = connection.execute(text("SELECT role, content FROM chat_messages")).all()
        assert len(rows) == 1
        assert rows[0][1] == "旧数据：保修期为一年"

        # 4. 其余表被正常创建
        assert {"chat_sessions", "knowledge_bases", "documents", "chunks", "users"} <= {
            name for name in _all_table_names()
        }
    finally:
        dispose_engine()
        clear_settings_override()


def test_init_db_idempotent(tmp_path: Path) -> None:
    """重复执行 init_db 不报错（补列操作幂等）。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    cfg.mysql.url_override = f"sqlite:///{(tmp_path / 'idem.db').as_posix()}"

    override_settings(cfg)
    try:
        init_engine(cfg, force=True)
        init_db(cfg)
        init_db(cfg)  # 第二次：无列需要补充
        columns = _column_names("chat_messages")
        assert "feedback" in columns
    finally:
        dispose_engine()
        clear_settings_override()


def _all_table_names() -> list[str]:
    """列出 SQLite 中全部表名。"""
    with get_engine().connect() as connection:
        rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    return [str(row[0]) for row in rows]
