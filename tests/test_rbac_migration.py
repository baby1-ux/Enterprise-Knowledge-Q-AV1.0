"""RBAC 自动迁移测试：旧库升级后自动补 visibility 列、回填默认角色、ensure_default_roles 幂等。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.core.config import Settings, clear_settings_override, override_settings
from app.db.session import dispose_engine, get_engine, init_db, init_engine


def test_init_db_seeds_default_roles(tmp_path: Path) -> None:
    """init_db 完成后，admin / staff / viewer 三个系统角色均存在。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    cfg.mysql.url_override = f"sqlite:///{(tmp_path / 'roles.db').as_posix()}"

    override_settings(cfg)
    try:
        init_engine(cfg, force=True)
        init_db(cfg)

        with get_engine().connect() as connection:
            codes = [row[0] for row in connection.execute(text("SELECT code FROM roles ORDER BY id")).all()]
        assert codes == ["admin", "staff", "viewer"]
    finally:
        dispose_engine()
        clear_settings_override()


def test_init_db_backfills_viewer_for_existing_users(tmp_path: Path) -> None:
    """旧库已有 user 但没有 user_roles 时，init_db 自动补 viewer。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    cfg.mysql.url_override = f"sqlite:///{(tmp_path / 'backfill.db').as_posix()}"

    from sqlalchemy import create_engine

    legacy_engine = create_engine(cfg.mysql.url_override)
    with legacy_engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE users ("
            " id INTEGER NOT NULL PRIMARY KEY,"
            " username VARCHAR(64) NOT NULL UNIQUE,"
            " password_hash VARCHAR(255) NOT NULL,"
            " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "INSERT INTO users (username, password_hash) VALUES ('legacy_alice', 'x'), ('legacy_bob', 'y')"
        ))
    legacy_engine.dispose()

    override_settings(cfg)
    try:
        init_engine(cfg, force=True)
        init_db(cfg)

        with get_engine().connect() as connection:
            rows = connection.execute(text(
                "SELECT u.username, r.code FROM users u "
                "LEFT JOIN user_roles ur ON ur.user_id = u.id "
                "LEFT JOIN roles r ON r.id = ur.role_id"
            )).all()
        by_user = {row[0]: row[1] for row in rows}
        assert by_user.get("legacy_alice") == "viewer"
        assert by_user.get("legacy_bob") == "viewer"
    finally:
        dispose_engine()
        clear_settings_override()


def test_init_db_idempotent_under_rbac(tmp_path: Path) -> None:
    """重复 init_db 不报错。"""
    cfg = Settings()
    cfg.project_root = tmp_path
    cfg.mysql.url_override = f"sqlite:///{(tmp_path / 'idem_rbac.db').as_posix()}"

    override_settings(cfg)
    try:
        init_engine(cfg, force=True)
        init_db(cfg)
        init_db(cfg)
        init_db(cfg)
        with get_engine().connect() as connection:
            role_count = connection.execute(text("SELECT COUNT(*) FROM roles")).scalar()
        assert role_count == 3
    finally:
        dispose_engine()
        clear_settings_override()
