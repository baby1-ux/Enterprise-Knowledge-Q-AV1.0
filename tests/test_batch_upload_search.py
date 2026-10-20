"""批量上传、跨库分块搜索与知识库名称搜索测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import SAMPLE_MARKDOWN, create_kb

DOC_A = """# 产品保修政策

公司所有电子产品自购买之日起提供一年免费保修服务。
"""

DOC_B = """# 售后服务规范

客服需在 2 个工作日内响应保修申请，并安排上门取件或寄修。
"""


def _upload_batch(
    client: TestClient,
    headers: dict[str, str],
    kb_id: int,
    files: list[tuple[str, bytes]],
    chunk_size: int = 150,
    chunk_overlap: int = 20,
    retrieval_mode: str = "dense",
) -> dict:
    """调用批量上传接口，返回响应体。"""
    response = client.post(
        f"/api/kb/{kb_id}/documents/batch",
        headers=headers,
        files=[("files", (name, content, "text/markdown")) for name, content in files],
        data={
            "chunk_size": str(chunk_size),
            "chunk_overlap": str(chunk_overlap),
            "retrieval_mode": retrieval_mode,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


# ---------------------------------------------------------------- 批量上传
def test_batch_upload_multiple_files(client: TestClient, auth_headers: dict[str, str]) -> None:
    """一次上传多个文件全部成功入库（测试客户端中后台任务同步执行）。"""
    kb = create_kb(client, auth_headers)
    data = _upload_batch(
        client,
        auth_headers,
        kb["id"],
        [("保修政策.md", DOC_A.encode("utf-8")), ("售后规范.md", DOC_B.encode("utf-8"))],
    )

    assert len(data["uploaded"]) == 2
    assert data["failed"] == []
    filenames = {item["filename"] for item in data["uploaded"]}
    assert filenames == {"保修政策.md", "售后规范.md"}

    # 解析完成，分块已写入
    documents = client.get(f"/api/kb/{kb['id']}/documents", headers=auth_headers).json()["data"]
    assert len(documents) == 2
    assert all(item["status"] == "success" for item in documents)
    assert all(item["chunk_count"] >= 1 for item in documents)


def test_batch_upload_partial_failure(client: TestClient, auth_headers: dict[str, str]) -> None:
    """部分文件失败不影响其它文件：失败项带文件名与中文原因。"""
    kb = create_kb(client, auth_headers)
    data = _upload_batch(
        client,
        auth_headers,
        kb["id"],
        [("保修政策.md", DOC_A.encode("utf-8")), ("安装包.exe", b"MZ...")],
    )

    assert len(data["uploaded"]) == 1
    assert data["uploaded"][0]["filename"] == "保修政策.md"
    assert len(data["failed"]) == 1
    assert data["failed"][0]["filename"] == "安装包.exe"
    assert "不支持的文件类型" in data["failed"][0]["message"]

    documents = client.get(f"/api/kb/{kb['id']}/documents", headers=auth_headers).json()["data"]
    assert len(documents) == 1


def test_batch_upload_rejects_too_many_files(client: TestClient, auth_headers: dict[str, str]) -> None:
    """单次超过 20 个文件返回 400。"""
    kb = create_kb(client, auth_headers)
    files = [(f"文档{index}.md", DOC_A.encode("utf-8")) for index in range(21)]
    response = client.post(
        f"/api/kb/{kb['id']}/documents/batch",
        headers=auth_headers,
        files=[("files", (name, content, "text/markdown")) for name, content in files],
        data={"chunk_size": "150", "chunk_overlap": "20", "retrieval_mode": "dense"},
    )
    assert response.status_code == 400
    assert "20" in response.json()["message"]


def test_batch_upload_invalid_params(client: TestClient, auth_headers: dict[str, str]) -> None:
    """批量上传同样校验切块参数。"""
    kb = create_kb(client, auth_headers)
    response = client.post(
        f"/api/kb/{kb['id']}/documents/batch",
        headers=auth_headers,
        files=[("files", ("a.md", DOC_A.encode("utf-8"), "text/markdown"))],
        data={"chunk_size": "50", "chunk_overlap": "0", "retrieval_mode": "dense"},
    )
    assert response.status_code == 400
    assert "切块大小" in response.json()["message"]


# ---------------------------------------------------------------- 跨库分块搜索
def _prepare_two_kbs(client: TestClient, headers: dict[str, str]) -> tuple[dict, dict]:
    """建两个知识库并分别上传文档。"""
    kb1 = create_kb(client, headers, name="产品库")
    kb2 = create_kb(client, headers, name="客服库")
    _upload_batch(client, headers, kb1["id"], [("保修政策.md", DOC_A.encode("utf-8"))])
    _upload_batch(client, headers, kb2["id"], [("售后规范.md", DOC_B.encode("utf-8"))])
    return kb1, kb2


def test_search_chunks_cross_kb(client: TestClient, auth_headers: dict[str, str]) -> None:
    """跨库搜索：命中多个知识库的分块，结果带文档名与知识库名。"""
    _prepare_two_kbs(client, auth_headers)

    response = client.get(
        "/api/kb/chunks/search", headers=auth_headers, params={"keyword": "保修"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 2
    kb_names = {item["kb_name"] for item in data["items"]}
    doc_names = {item["doc_name"] for item in data["items"]}
    assert "产品库" in kb_names
    assert "客服库" in kb_names
    assert "保修政策.md" in doc_names
    assert "售后规范.md" in doc_names
    assert all(item["content"] for item in data["items"])


def test_search_chunks_scoped_by_kb_ids(client: TestClient, auth_headers: dict[str, str]) -> None:
    """指定 kb_ids 时只在选定知识库内搜索。"""
    kb1, _ = _prepare_two_kbs(client, auth_headers)
    response = client.get(
        "/api/kb/chunks/search", headers=auth_headers, params={"keyword": "保修", "kb_ids": [kb1["id"]]}
    )
    data = response.json()["data"]
    assert data["total"] >= 1
    assert {item["kb_name"] for item in data["items"]} == {"产品库"}


def test_search_chunks_requires_keyword(client: TestClient, auth_headers: dict[str, str]) -> None:
    """缺少关键字返回 422。"""
    response = client.get("/api/kb/chunks/search", headers=auth_headers)
    assert response.status_code == 422


def test_search_chunks_no_match(client: TestClient, auth_headers: dict[str, str]) -> None:
    """无匹配时返回空列表。"""
    _prepare_two_kbs(client, auth_headers)
    response = client.get(
        "/api/kb/chunks/search", headers=auth_headers, params={"keyword": "不存在的关键字xyz"}
    )
    data = response.json()["data"]
    assert data["total"] == 0
    assert data["items"] == []


def test_search_chunks_pagination(client: TestClient, auth_headers: dict[str, str]) -> None:
    """分页参数生效。"""
    _prepare_two_kbs(client, auth_headers)
    response = client.get(
        "/api/kb/chunks/search", headers=auth_headers, params={"keyword": "保修", "page": 1, "page_size": 1}
    )
    data = response.json()["data"]
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert len(data["items"]) == 1
    assert data["total"] >= 2


def test_search_chunks_isolated_by_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    """跨库搜索按用户隔离。"""
    from tests.conftest import login_user, register_user

    _prepare_two_kbs(client, auth_headers)

    register_user(client, username="search_other")
    other_headers = {"Authorization": f"Bearer {login_user(client, username='search_other')}"}
    response = client.get("/api/kb/chunks/search", headers=other_headers, params={"keyword": "保修"})
    data = response.json()["data"]
    assert data["total"] == 0
    assert data["items"] == []


# ---------------------------------------------------------------- 知识库名称搜索
def test_list_kb_keyword_search(client: TestClient, auth_headers: dict[str, str]) -> None:
    """知识库列表支持名称关键字过滤。"""
    create_kb(client, auth_headers, name="产品保修库")
    create_kb(client, auth_headers, name="人事制度库")

    response = client.get("/api/kb/", headers=auth_headers, params={"keyword": "保修"})
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["name"] == "产品保修库"

    # 无关键字时返回全部
    all_response = client.get("/api/kb/", headers=auth_headers)
    assert len(all_response.json()["data"]) == 2


def test_list_kb_keyword_no_match(client: TestClient, auth_headers: dict[str, str]) -> None:
    """名称搜索无匹配时返回空列表。"""
    create_kb(client, auth_headers, name="产品保修库")
    response = client.get("/api/kb/", headers=auth_headers, params={"keyword": "财务报表"})
    assert response.json()["data"] == []
