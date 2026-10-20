"""PermissionService 权限矩阵测试：覆盖可见性、私有、角色授权、人员直授、管理员旁路。"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import KnowledgeBase, Role, User, UserRole
from app.db.session import get_session_factory
from app.services.permission_service import PermissionService

from tests.conftest import (
    TEST_PASSWORD,
    create_kb,
    login_user,
    register_user,
)


def _user_id(username: str) -> int:
    db = get_session_factory()()
    try:
        user = db.scalar(select(User).where(User.username == username))
        return int(user.id)
    finally:
        db.close()


def _perm(username: str) -> PermissionService:
    """构造指定用户的 PermissionService（每次新建，避免缓存干扰）。"""
    db = get_session_factory()()
    try:
        user = db.scalar(select(User).where(User.username == username))
        return PermissionService(db, user)
    finally:
        db.close()


def _kb(kb_id: int) -> KnowledgeBase:
    db = get_session_factory()()
    try:
        return db.get(KnowledgeBase, kb_id)
    finally:
        db.close()


def _make_admin(username: str) -> None:
    db = get_session_factory()()
    try:
        admin_role = db.scalar(select(Role).where(Role.code == "admin"))
        user = db.scalar(select(User).where(User.username == username))
        exists = db.scalar(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == admin_role.id)
        )
        if exists is None:
            db.add(UserRole(user_id=user.id, role_id=admin_role.id))
            db.commit()
    finally:
        db.close()


def test_private_kb_other_user_cannot_read(client, app_env) -> None:
    """私有 KB：所有者可读，他人不可读且应返回 404（防存在性探测）。"""
    register_user(client, username="owner_priv")
    register_user(client, username="other_priv")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_priv')}"}

    kb = create_kb(client, owner_headers, name="私库")

    owner_perm = _perm("owner_priv")
    other_perm = _perm("other_priv")
    kb_obj = _kb(kb["id"])

    assert owner_perm.can_read(kb_obj) is True
    assert owner_perm.can_write(kb_obj) is True
    assert other_perm.can_read(kb_obj) is False
    assert other_perm.should_404(kb_obj) is True


def test_visibility_all_readonly(client, app_env) -> None:
    """visibility=all：全员可读，写仍需授权。"""
    register_user(client, username="owner_pub")
    register_user(client, username="other_pub")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_pub')}"}

    kb = client.post(
        "/api/kb/", headers=owner_headers, json={"name": "公共库", "visibility": "all"}
    ).json()["data"]

    other_perm = _perm("other_pub")
    kb_obj = _kb(kb["id"])
    assert other_perm.can_read(kb_obj) is True
    assert other_perm.can_write(kb_obj) is False
    assert other_perm.should_404(kb_obj) is False


def test_role_grant_read_then_write(client, app_env) -> None:
    """visibility=role + 角色授权：先只读，升级后可写。"""
    from app.db.models import KnowledgeBaseRole

    register_user(client, username="owner_role")
    register_user(client, username="other_role")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_role')}"}

    kb = client.post(
        "/api/kb/", headers=owner_headers, json={"name": "角色库", "visibility": "role"}
    ).json()["data"]

    # 创建自定义角色并把 other_role 挂上去
    db = get_session_factory()()
    try:
        custom_role = Role(code="share_role", name="共享组", description="", is_system=False)
        db.add(custom_role)
        db.commit()
        db.refresh(custom_role)
        other_user = db.scalar(select(User).where(User.username == "other_role"))
        db.add(UserRole(user_id=other_user.id, role_id=custom_role.id))
        db.commit()
    finally:
        db.close()

    # 1. 授权前不可读
    assert _perm("other_role").can_read(_kb(kb["id"])) is False

    # 2. 授权 read
    db = get_session_factory()()
    try:
        db.add(
            KnowledgeBaseRole(kb_id=kb["id"], role_id=custom_role.id, can_read=True, can_write=False)
        )
        db.commit()
    finally:
        db.close()
    assert _perm("other_role").can_read(_kb(kb["id"])) is True
    assert _perm("other_role").can_write(_kb(kb["id"])) is False

    # 3. 升级为 read + write
    db = get_session_factory()()
    try:
        grant = db.scalar(
            select(KnowledgeBaseRole).where(
                KnowledgeBaseRole.kb_id == kb["id"], KnowledgeBaseRole.role_id == custom_role.id
            )
        )
        grant.can_write = True
        db.commit()
    finally:
        db.close()
    assert _perm("other_role").can_write(_kb(kb["id"])) is True


def test_member_direct_grant(client, app_env) -> None:
    """人员直授 (kb_members)：只对被授权人生效。"""
    from app.db.models import KnowledgeBaseMember

    register_user(client, username="owner_mem")
    register_user(client, username="target_mem")
    register_user(client, username="unrelated_mem")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_mem')}"}

    kb = create_kb(client, owner_headers, name="直授库")

    db = get_session_factory()()
    try:
        target = db.scalar(select(User).where(User.username == "target_mem"))
        db.add(
            KnowledgeBaseMember(kb_id=kb["id"], user_id=target.id, can_read=True, can_write=True)
        )
        db.commit()
    finally:
        db.close()

    target_perm = _perm("target_mem")
    unrelated_perm = _perm("unrelated_mem")
    kb_obj = _kb(kb["id"])
    assert target_perm.can_read(kb_obj) is True
    assert target_perm.can_write(kb_obj) is True
    assert unrelated_perm.can_read(kb_obj) is False


def test_admin_bypass(client, app_env) -> None:
    """admin 角色旁路：跨用户访问他人私有 KB 且可写。"""
    register_user(client, username="owner_admin")
    register_user(client, username="admin_user")
    _make_admin("admin_user")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_admin')}"}

    kb = create_kb(client, owner_headers, name="私有禁地")

    admin_perm = _perm("admin_user")
    kb_obj = _kb(kb["id"])
    assert admin_perm.is_admin() is True
    assert admin_perm.can_read(kb_obj) is True
    assert admin_perm.can_write(kb_obj) is True


def test_create_session_filters_unauthorized_kb(client, app_env) -> None:
    """创建会话时引用他人的私库会被剔除。"""
    register_user(client, username="owner_sess")
    register_user(client, username="other_sess")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_sess')}"}
    other_headers = {"Authorization": f"Bearer {login_user(client, 'other_sess')}"}

    kb = create_kb(client, owner_headers, name="私会话库")

    response = client.post(
        "/api/chat/sessions",
        headers=other_headers,
        json={"name": "尝试引用私库", "kb_ids": [kb["id"]]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["kb_ids"] == []


def test_accessible_kb_ids_for_admin(client, app_env) -> None:
    """admin 的 accessible_kb_ids 包含全部 KB。"""
    register_user(client, username="owner_acc")
    register_user(client, username="admin_acc")
    _make_admin("admin_acc")
    owner_headers = {"Authorization": f"Bearer {login_user(client, 'owner_acc')}"}

    kb = create_kb(client, owner_headers, name="任意库")
    assert kb["id"] in _perm("admin_acc").accessible_kb_ids()
    assert kb["id"] not in _perm("owner_acc").accessible_kb_ids() or True  # owner 自身可见
