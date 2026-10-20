"""系统统计接口测试：GET /api/system/stats（按用户隔离）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import SAMPLE_MARKDOWN, FakeLLM, create_kb, upload_markdown


def test_stats_empty_for_new_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    """新用户各项计数为 0。"""
    response = client.get("/api/system/stats", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["knowledge_base_count"] == 0
    assert data["document_count"] == 0
    assert data["chunk_count"] == 0
    assert data["session_count"] == 0
    assert data["message_count"] == 0
    assert data["answer_count"] == 0
    assert data["today_answer_count"] == 0


def test_stats_counts_after_usage(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """建库、上传、提问后统计数字正确。"""
    kb = create_kb(client, auth_headers)
    upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)
    session = client.post(
        "/api/chat/sessions", headers=auth_headers, json={"kb_ids": [kb["id"]], "name": "统计会话"}
    ).json()["data"]
    client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={"session_id": session["id"], "question": "保修期是多久？", "retrieval_mode": "dense"},
    )

    response = client.get("/api/system/stats", headers=auth_headers)
    data = response.json()["data"]
    assert data["knowledge_base_count"] == 1
    assert data["document_count"] == 1
    assert data["chunk_count"] >= 1
    assert data["session_count"] == 1
    assert data["message_count"] == 2  # 一问一答
    assert data["answer_count"] == 1
    assert data["today_answer_count"] == 1


def test_stats_requires_auth(client: TestClient) -> None:
    """未登录访问统计返回 401。"""
    assert client.get("/api/system/stats").status_code == 401


def test_stats_isolated_by_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    """统计按用户隔离：其他用户的数据不计入。"""
    from tests.conftest import login_user, register_user

    create_kb(client, auth_headers, name="我的知识库")

    register_user(client, username="stats_other")
    other_headers = {"Authorization": f"Bearer {login_user(client, username='stats_other')}"}
    data = client.get("/api/system/stats", headers=other_headers).json()["data"]

    assert data["knowledge_base_count"] == 0
    assert data["document_count"] == 0
    assert data["session_count"] == 0
