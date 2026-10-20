"""KB 可见性 + 检索隔离集成测试：知识库列表、跨库搜索、统计、会话越权防护。"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import KnowledgeBaseRole, Role, User, UserRole
from app.db.session import get_session_factory

from tests.conftest import (
    SAMPLE_MARKDOWN,
    create_kb,
    login_user,
    register_user,
    upload_markdown,
)


def _h(username: str) -> dict[str, str]:
    """用户名 → 鉴权请求头。"""
    return {"Authorization": f"Bearer {login_user(client=None, username=username)}"}


def _headers(client, username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login_user(client, username)}"}


def _grant_staff_role(username: str) -> int:
    """给用户挂上 staff 角色，返回 role_id。"""
    db = get_session_factory()()
    try:
        staff_role = db.scalar(select(Role).where(Role.code == "staff"))
        user = db.scalar(select(User).where(User.username == username))
        exists = db.scalar(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == staff_role.id)
        )
        if exists is None:
            db.add(UserRole(user_id=user.id, role_id=staff_role.id))
            db.commit()
        return int(staff_role.id)
    finally:
        db.close()


def test_kb_list_filters_by_visibility(client, app_env) -> None:
    """三个 KB（私/角色/全员）：不同身份看到的集合不同。"""
    register_user(client, username="owner_3kbs")
    register_user(client, username="staff_3kbs")
    register_user(client, username="viewer_3kbs")

    owner_headers = _headers(client, "owner_3kbs")
    staff_headers = _headers(client, "staff_3kbs")
    viewer_headers = _headers(client, "viewer_3kbs")

    private_id = client.post(
        "/api/kb/", headers=owner_headers, json={"name": "私库"}
    ).json()["data"]["id"]
    role_id = client.post(
        "/api/kb/", headers=owner_headers, json={"name": "角色库", "visibility": "role"}
    ).json()["data"]["id"]
    all_id = client.post(
        "/api/kb/", headers=owner_headers, json={"name": "全员库", "visibility": "all"}
    ).json()["data"]["id"]

    # staff 用户挂 staff 角色，并把角色库授权给 staff（只读）
    staff_role_id = _grant_staff_role("staff_3kbs")
    db = get_session_factory()()
    try:
        db.add(
            KnowledgeBaseRole(kb_id=role_id, role_id=staff_role_id, can_read=True, can_write=False)
        )
        db.commit()
    finally:
        db.close()

    # owner：全部 3 个
    owner_list = client.get("/api/kb/", headers=owner_headers).json()["data"]
    assert {kb["id"] for kb in owner_list} == {private_id, role_id, all_id}

    # staff：角色库 + 全员库（私库不可见）
    staff_list = client.get("/api/kb/", headers=staff_headers).json()["data"]
    assert {kb["id"] for kb in staff_list} == {role_id, all_id}
    staff_role_kb = next(kb for kb in staff_list if kb["id"] == role_id)
    assert staff_role_kb["can_write"] is False
    assert staff_role_kb["visibility"] == "role"

    # viewer：仅全员库，且只读
    viewer_list = client.get("/api/kb/", headers=viewer_headers).json()["data"]
    assert {kb["id"] for kb in viewer_list} == {all_id}
    assert viewer_list[0]["can_write"] is False


def test_readonly_user_cannot_upload_document(client, app_env) -> None:
    """只读权限（visibility=all 的旁观者）上传文档 → 403。"""
    register_user(client, username="ro_owner")
    register_user(client, username="ro_visitor")
    owner_headers = _headers(client, "ro_owner")
    visitor_headers = _headers(client, "ro_visitor")

    kb = client.post(
        "/api/kb/", headers=owner_headers, json={"name": "公开只读库", "visibility": "all"}
    ).json()["data"]

    response = client.post(
        f"/api/kb/{kb['id']}/documents",
        headers=visitor_headers,
        files={"file": ("a.md", SAMPLE_MARKDOWN.encode("utf-8"), "text/markdown")},
        data={"chunk_size": "200", "chunk_overlap": "20", "retrieval_mode": "dense"},
    )
    assert response.status_code == 403


def test_search_chunks_filters_by_accessible(client, app_env) -> None:
    """跨库分块搜索只命中当前用户可访问的 KB。"""
    register_user(client, username="search_owner")
    register_user(client, username="search_other")
    owner_headers = _headers(client, "search_owner")
    other_headers = _headers(client, "search_other")

    public_id = create_kb(client, owner_headers, name="全员可搜")["id"]
    upload_markdown(client, owner_headers, public_id, SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)
    client.put(
        f"/api/kb/{public_id}", headers=owner_headers,
        json={"visibility": "all", "name": "全员可搜"}
    )

    private_id = create_kb(client, other_headers, name="私有可搜")["id"]
    upload_markdown(client, other_headers, private_id, SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)

    # owner 搜索：只命中自己可访问的（public，不含 other 的 private）
    data = client.get(
        "/api/kb/chunks/search", headers=owner_headers, params={"keyword": "保修"}
    ).json()["data"]
    assert data["total"] >= 1
    assert {item["kb_id"] for item in data["items"]} == {public_id}

    # other 搜索：public（all 可见）+ private 自己所有
    data = client.get(
        "/api/kb/chunks/search", headers=other_headers, params={"keyword": "保修"}
    ).json()["data"]
    assert {item["kb_id"] for item in data["items"]} <= {public_id, private_id}
    assert private_id in {item["kb_id"] for item in data["items"]}


def test_stats_counts_accessible(client, app_env) -> None:
    """统计按可访问 KB 计数。"""
    register_user(client, username="stat_owner")
    register_user(client, username="stat_viewer")
    owner_headers = _headers(client, "stat_owner")
    viewer_headers = _headers(client, "stat_viewer")

    public_id = create_kb(client, owner_headers, name="全员统计")["id"]
    upload_markdown(client, owner_headers, public_id, SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)
    client.put(f"/api/kb/{public_id}", headers=owner_headers, json={"visibility": "all"})

    private_id = create_kb(client, owner_headers, name="私统计")["id"]
    upload_markdown(client, owner_headers, private_id, SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)

    owner_stats = client.get("/api/system/stats", headers=owner_headers).json()["data"]
    viewer_stats = client.get("/api/system/stats", headers=viewer_headers).json()["data"]

    assert owner_stats["knowledge_base_count"] == 2
    assert owner_stats["document_count"] == 2
    assert viewer_stats["knowledge_base_count"] == 1
    assert viewer_stats["document_count"] == 1


def test_me_returns_roles_and_admin_flag(client, app_env) -> None:
    """/me 返回 roles 与 is_admin。"""
    register_user(client, username="me_test")
    response = client.get("/api/auth/me", headers=_headers(client, "me_test"))
    data = response.json()["data"]
    assert "viewer" in data["roles"]
    assert data["is_admin"] is False
