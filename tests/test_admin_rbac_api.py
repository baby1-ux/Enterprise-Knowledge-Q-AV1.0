"""管理员 RBAC 接口测试：角色管理、用户角色分配、知识库授权。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import (
    TEST_PASSWORD,
    create_kb,
    login_user,
    register_user,
)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login_user(client, username)}"}


def _create_admin(client: TestClient, username: str) -> str:
    """注册并把用户提为 admin（直接操作数据库，绕开白名单）。"""
    from sqlalchemy import select

    from app.db.models import Role, User, UserRole
    from app.db.session import get_session_factory

    register_user(client, username=username)
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
    return login_user(client, username)


def test_list_roles_requires_admin(client: TestClient, app_env) -> None:
    """非 admin 访问管理接口 → 403。"""
    register_user(client, username="roles_user")
    response = client.get("/api/admin/roles", headers=_headers(client, "roles_user"))
    assert response.status_code == 403


def test_list_roles_as_admin(client: TestClient, app_env) -> None:
    """admin 可看到全部角色（含系统内置 + 用户数 / KB 数统计）。"""
    admin_token = _create_admin(client, "roles_admin")
    response = client.get("/api/admin/roles", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    data = response.json()["data"]
    codes = {role["code"] for role in data}
    assert {"admin", "staff", "viewer"} <= codes
    admin_role = next(role for role in data if role["code"] == "admin")
    assert admin_role["is_system"] is True


def test_create_update_delete_custom_role(client: TestClient, app_env) -> None:
    """自定义角色 CRUD。"""
    admin_token = _create_admin(client, "rbac_admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    create = client.post(
        "/api/admin/roles", headers=admin_headers,
        json={"code": "sales", "name": "销售组", "description": "面向销售"},
    )
    assert create.status_code == 200
    role_id = create.json()["data"]["id"]

    update = client.put(
        f"/api/admin/roles/{role_id}", headers=admin_headers,
        json={"code": "sales", "name": "销售组（更新）", "description": "已更新"},
    )
    assert update.status_code == 200
    assert update.json()["data"]["name"] == "销售组（更新）"

    delete = client.delete(f"/api/admin/roles/{role_id}", headers=admin_headers)
    assert delete.status_code == 200


def test_cannot_delete_system_role(client: TestClient, app_env) -> None:
    """系统内置角色不可删除。"""
    admin_token = _create_admin(client, "sysadmin_test")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    from sqlalchemy import select

    from app.db.models import Role
    from app.db.session import get_session_factory

    db = get_session_factory()()
    try:
        viewer_role = db.scalar(select(Role).where(Role.code == "viewer"))
        response = client.delete(
            f"/api/admin/roles/{viewer_role.id}", headers=admin_headers
        )
        assert response.status_code == 400
        assert "系统内置" in response.json()["message"]
    finally:
        db.close()


def test_list_users_and_assign_roles(client: TestClient, app_env) -> None:
    """用户列表 + 为用户分配角色（覆盖式）。"""
    admin_token = _create_admin(client, "assign_admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    register_user(client, username="assign_target")

    users = client.get("/api/admin/users", headers=admin_headers).json()["data"]
    target = next(user for user in users if user["username"] == "assign_target")
    assert "viewer" in target["roles"]

    from sqlalchemy import select

    from app.db.models import Role
    from app.db.session import get_session_factory

    db = get_session_factory()()
    try:
        staff_role = db.scalar(select(Role).where(Role.code == "staff"))
        response = client.put(
            f"/api/admin/users/{target['id']}/roles",
            headers=admin_headers,
            json={"role_ids": [staff_role.id]},
        )
        assert response.status_code == 200

        users = client.get("/api/admin/users", headers=admin_headers).json()["data"]
        target = next(user for user in users if user["username"] == "assign_target")
        assert target["roles"] == ["staff"]
    finally:
        db.close()


def test_assign_user_roles_requires_at_least_one(client: TestClient, app_env) -> None:
    """分配角色时不允许清空。"""
    admin_token = _create_admin(client, "least_admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    register_user(client, username="least_user")
    users = client.get("/api/admin/users", headers=admin_headers).json()["data"]
    target = next(user for user in users if user["username"] == "least_user")
    response = client.put(
        f"/api/admin/users/{target['id']}/roles",
        headers=admin_headers,
        json={"role_ids": []},
    )
    assert response.status_code == 400
    assert "至少" in response.json()["message"]


def test_kb_permission_update_for_owner(client: TestClient, app_env) -> None:
    """KB 所有者可配置角色授权与人员直授。"""
    from sqlalchemy import select

    from app.db.models import Role, User
    from app.db.session import get_session_factory

    register_user(client, username="perm_owner")
    register_user(client, username="perm_target")
    register_user(client, username="perm_target2")
    _create_admin(client, "perm_admin")

    owner_headers = _headers(client, "perm_owner")
    kb = create_kb(client, owner_headers, name="授权库")

    db = get_session_factory()()
    try:
        staff_role = db.scalar(select(Role).where(Role.code == "staff"))
        target_user = db.scalar(select(User).where(User.username == "perm_target"))

        response = client.put(
            f"/api/kb/{kb['id']}", headers=owner_headers, json={"visibility": "role"}
        )
        assert response.status_code == 200

        response = client.put(
            f"/api/admin/kb/{kb['id']}/permission",
            headers=owner_headers,
            json={
                "role_grants": [
                    {"role_id": staff_role.id, "can_read": True, "can_write": True}
                ],
                "member_grants": [
                    {"user_id": target_user.id, "can_read": True, "can_write": False}
                ]
            }
        )
        assert response.status_code == 200
        result = response.json()["data"]
        assert len(result["roles"]) == 1
        assert result["roles"][0]["role_code"] == "staff"
        assert result["roles"][0]["can_write"] is True
        assert len(result["members"]) == 1
        assert result["members"][0]["username"] == "perm_target"
        assert result["members"][0]["can_write"] is False
    finally:
        db.close()


def test_kb_permission_requires_owner_or_admin(client: TestClient, app_env) -> None:
    """非所有者、非 admin 查看 KB 授权 → 403。"""
    register_user(client, username="kb_owner")
    register_user(client, username="kb_stranger")
    owner_headers = _headers(client, "kb_owner")
    stranger_headers = _headers(client, "kb_stranger")
    kb = create_kb(client, owner_headers, name="独门库")
    response = client.get(
        f"/api/admin/kb/{kb['id']}/permission",
        headers=stranger_headers,
    )
    assert response.status_code == 403
