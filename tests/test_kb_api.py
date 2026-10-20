"""知识库接口测试：知识库管理、文档上传解析、分块预览编辑删除。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import SAMPLE_MARKDOWN, create_kb, fetch_captcha, login_user, register_user, upload_markdown


def test_create_and_list_knowledge_base(client: TestClient, auth_headers: dict[str, str]) -> None:
    """创建知识库后可在列表中看到。"""
    kb = create_kb(client, auth_headers, name="售后知识库")
    assert kb["name"] == "售后知识库"
    assert kb["doc_count"] == 0

    response = client.get("/api/kb/", headers=auth_headers)
    items = response.json()["data"]
    assert any(item["id"] == kb["id"] for item in items)


def test_create_duplicate_knowledge_base(client: TestClient, auth_headers: dict[str, str]) -> None:
    """同名知识库创建失败。"""
    create_kb(client, auth_headers, name="重复名称")
    response = client.post("/api/kb/", headers=auth_headers, json={"name": "重复名称"})
    assert response.status_code == 400
    assert "同名知识库" in response.json()["message"]


def test_update_knowledge_base(client: TestClient, auth_headers: dict[str, str]) -> None:
    """可修改知识库名称与描述。"""
    kb = create_kb(client, auth_headers)
    response = client.put(
        f"/api/kb/{kb['id']}", headers=auth_headers, json={"name": "新名称", "description": "新描述"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "新名称"
    assert data["description"] == "新描述"


def test_upload_markdown_and_ingest(client: TestClient, auth_headers: dict[str, str]) -> None:
    """上传 Markdown 后自动解析、切块并写入向量库。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    assert document["filename"] == "产品手册.md"
    assert document["chunk_size"] == 200

    status_response = client.get(f"/api/kb/documents/{document['id']}/status", headers=auth_headers)
    status = status_response.json()["data"]
    assert status["status"] == "success", status
    assert status["chunk_count"] > 0

    list_response = client.get(f"/api/kb/{kb['id']}/documents", headers=auth_headers)
    documents = list_response.json()["data"]
    assert documents[0]["status"] == "success"
    assert documents[0]["chunk_count"] > 0


def test_chunk_list_pagination_and_keyword(client: TestClient, auth_headers: dict[str, str]) -> None:
    """分块列表支持分页与关键字过滤。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN, chunk_size=120, chunk_overlap=10)

    page_response = client.get(
        f"/api/kb/documents/{document['id']}/chunks?page=1&page_size=2", headers=auth_headers
    )
    page = page_response.json()["data"]
    assert page["page"] == 1
    assert page["page_size"] == 2
    assert len(page["items"]) <= 2
    assert page["total"] >= 1

    keyword_response = client.get(
        f"/api/kb/documents/{document['id']}/chunks?keyword=保修", headers=auth_headers
    )
    keyword_page = keyword_response.json()["data"]
    assert keyword_page["total"] >= 1
    assert all("保修" in item["content"] for item in keyword_page["items"])


def test_update_chunk_content(client: TestClient, auth_headers: dict[str, str]) -> None:
    """编辑分块内容后返回新内容。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    chunks = client.get(f"/api/kb/documents/{document['id']}/chunks", headers=auth_headers).json()["data"]["items"]
    chunk_id = chunks[0]["id"]

    response = client.put(
        f"/api/kb/chunks/{chunk_id}", headers=auth_headers, json={"content": "保修期调整为两年（人工修改）。"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content"] == "保修期调整为两年（人工修改）。"


def test_update_chunk_rejects_empty_content(client: TestClient, auth_headers: dict[str, str]) -> None:
    """空内容不能保存。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    chunks = client.get(f"/api/kb/documents/{document['id']}/chunks", headers=auth_headers).json()["data"]["items"]
    response = client.put(f"/api/kb/chunks/{chunks[0]['id']}", headers=auth_headers, json={"content": "   "})
    assert response.status_code == 422


def test_toggle_chunk_enabled(client: TestClient, auth_headers: dict[str, str]) -> None:
    """分块可启用/禁用。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    chunk_id = client.get(f"/api/kb/documents/{document['id']}/chunks", headers=auth_headers).json()["data"]["items"][0]["id"]

    response = client.put(f"/api/kb/chunks/{chunk_id}/enabled", headers=auth_headers, json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False


def test_delete_chunk(client: TestClient, auth_headers: dict[str, str]) -> None:
    """删除分块后总数减少。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    before = client.get(f"/api/kb/documents/{document['id']}/chunks", headers=auth_headers).json()["data"]
    chunk_id = before["items"][0]["id"]

    response = client.delete(f"/api/kb/chunks/{chunk_id}", headers=auth_headers)
    assert response.status_code == 200

    after = client.get(f"/api/kb/documents/{document['id']}/chunks", headers=auth_headers).json()["data"]
    assert after["total"] == before["total"] - 1


def test_delete_document(client: TestClient, auth_headers: dict[str, str]) -> None:
    """删除文档后列表为空。"""
    kb = create_kb(client, auth_headers)
    document = upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    response = client.delete(f"/api/kb/documents/{document['id']}", headers=auth_headers)
    assert response.status_code == 200
    documents = client.get(f"/api/kb/{kb['id']}/documents", headers=auth_headers).json()["data"]
    assert documents == []


def test_delete_knowledge_base(client: TestClient, auth_headers: dict[str, str]) -> None:
    """删除知识库后列表中不再出现。"""
    kb = create_kb(client, auth_headers, name="待删除知识库")
    upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN)
    response = client.delete(f"/api/kb/{kb['id']}", headers=auth_headers)
    assert response.status_code == 200
    items = client.get("/api/kb/", headers=auth_headers).json()["data"]
    assert all(item["id"] != kb["id"] for item in items)


def test_upload_unsupported_file_type(client: TestClient, auth_headers: dict[str, str]) -> None:
    """不支持的文件类型被拒绝。"""
    kb = create_kb(client, auth_headers)
    response = client.post(
        f"/api/kb/{kb['id']}/documents",
        headers=auth_headers,
        files={"file": ("数据.xyz", b"content", "application/octet-stream")},
        data={"chunk_size": "200", "chunk_overlap": "20", "retrieval_mode": "dense"},
    )
    assert response.status_code == 400
    assert "不支持的文件类型" in response.json()["message"]


def test_upload_invalid_chunk_params(client: TestClient, auth_headers: dict[str, str]) -> None:
    """非法切块参数被拒绝。"""
    kb = create_kb(client, auth_headers)
    response = client.post(
        f"/api/kb/{kb['id']}/documents",
        headers=auth_headers,
        files={"file": ("a.md", b"# title\n\ncontent", "text/markdown")},
        data={"chunk_size": "10", "chunk_overlap": "5", "retrieval_mode": "dense"},
    )
    assert response.status_code == 400
    assert "切块大小" in response.json()["message"]


def test_other_user_cannot_access_knowledge_base(client: TestClient, auth_headers: dict[str, str]) -> None:
    """其他用户无法访问他人知识库。"""
    kb = create_kb(client, auth_headers)
    register_user(client, username="other02")
    other_token = login_user(client, username="other02")
    other_headers = {"Authorization": f"Bearer {other_token}"}

    response = client.get(f"/api/kb/{kb['id']}/documents", headers=other_headers)
    assert response.status_code == 404
    assert "知识库不存在" in response.json()["message"]


def test_knowledge_base_requires_login(client: TestClient) -> None:
    """未登录访问知识库接口返回 401。"""
    response = client.get("/api/kb/")
    assert response.status_code == 401


def test_status_of_missing_document(client: TestClient, auth_headers: dict[str, str]) -> None:
    """查询不存在的文档返回 404。"""
    response = client.get("/api/kb/documents/99999/status", headers=auth_headers)
    assert response.status_code == 404
