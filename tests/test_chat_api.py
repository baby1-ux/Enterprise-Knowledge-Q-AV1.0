"""对话接口测试：模型参数、会话管理、消息历史、流式问答（使用假大模型）。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import SAMPLE_MARKDOWN, FakeLLM, create_kb, upload_markdown


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """解析 SSE 文本为 (event, data) 列表。"""
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event_name:
            payload = json.loads("".join(data_lines) or "{}")
            events.append((event_name, payload))
    return events


def test_models_endpoint(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """模型列表与默认参数可获取。"""
    response = client.get("/api/chat/models", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["models"][0]["value"] == "deepseek-chat"
    assert data["models"][0]["label"].startswith("DeepSeek")
    assert data["models"][1]["value"] == "deepseek-reasoner"
    assert data["defaults"]["history_rounds"] == 5
    assert data["defaults"]["model"] == "deepseek-chat"


def test_session_crud(client: TestClient, auth_headers: dict[str, str]) -> None:
    """会话支持新建、重命名、查询与删除。"""
    create_response = client.post(
        "/api/chat/sessions",
        headers=auth_headers,
        json={"name": "保修咨询", "kb_ids": [], "model": "deepseek-reasoner", "temperature": 0.5, "history_rounds": 3},
    )
    assert create_response.status_code == 200
    session = create_response.json()["data"]
    assert session["name"] == "保修咨询"
    assert session["model"] == "deepseek-reasoner"
    assert session["temperature"] == 0.5
    assert session["history_rounds"] == 3

    update_response = client.put(
        f"/api/chat/sessions/{session['id']}", headers=auth_headers, json={"name": "改名后的会话"}
    )
    assert update_response.json()["data"]["name"] == "改名后的会话"

    sessions = client.get("/api/chat/sessions", headers=auth_headers).json()["data"]
    assert any(item["id"] == session["id"] for item in sessions)

    delete_response = client.delete(f"/api/chat/sessions/{session['id']}", headers=auth_headers)
    assert delete_response.status_code == 200
    sessions = client.get("/api/chat/sessions", headers=auth_headers).json()["data"]
    assert all(item["id"] != session["id"] for item in sessions)


def test_session_default_name_and_kb_names(client: TestClient, auth_headers: dict[str, str]) -> None:
    """默认会话名为“新对话”，并回显知识库名称。"""
    kb = create_kb(client, auth_headers, name="对话知识库")
    response = client.post("/api/chat/sessions", headers=auth_headers, json={"kb_ids": [kb["id"]]})
    assert response.status_code == 200
    session = response.json()["data"]
    assert session["name"] == "新对话"
    assert session["kb_ids"] == [kb["id"]]

    sessions = client.get("/api/chat/sessions", headers=auth_headers).json()["data"]
    target = next(item for item in sessions if item["id"] == session["id"])
    assert target["kb_names"] == ["对话知识库"]


def test_stream_answer_with_knowledge_base(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """选择知识库提问：返回 start → retrieval → delta → done，并落库两条消息。"""
    kb = create_kb(client, auth_headers)
    upload_markdown(client, auth_headers, kb["id"], SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)
    session = client.post(
        "/api/chat/sessions", headers=auth_headers, json={"kb_ids": [kb["id"]], "name": "保修咨询"}
    ).json()["data"]

    response = client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={
            "session_id": session["id"],
            "question": "产品保修期是多久？",
            "kb_ids": [kb["id"]],
            "retrieval_mode": "dense",
            "history_rounds": 5,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "start"
    assert names[-1] == "done"
    assert "delta" in names

    # 流式增量拼接结果等于最终答案
    streamed = "".join(payload["content"] for name, payload in events if name == "delta")
    done_payload = events[-1][1]
    assert done_payload["answer"] == fake_llm.reply
    assert streamed == fake_llm.reply

    # 引用来源包含文档名
    retrieval_events = [payload for name, payload in events if name == "retrieval"]
    if retrieval_events:
        chunks = retrieval_events[0]["chunks"]
        assert chunks and chunks[0]["doc_name"] == "产品手册.md"

    messages = client.get(f"/api/chat/sessions/{session['id']}/messages", headers=auth_headers).json()["data"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "产品保修期是多久？"
    assert messages[1]["content"] == fake_llm.reply

    # 系统提示词包含检索到的参考资料
    system_message = fake_llm.last_messages()[0]
    assert system_message["role"] == "system"
    assert "参考资料" in system_message["content"]


def test_stream_answer_without_knowledge_base(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """未选择知识库时也能回答，并提示未检索到内容。"""
    session = client.post("/api/chat/sessions", headers=auth_headers, json={"kb_ids": []}).json()["data"]
    response = client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={"session_id": session["id"], "question": "你好，介绍一下你自己"},
    )
    events = parse_sse(response.text)
    assert events[0][0] == "start"
    assert events[-1][0] == "done"
    assert events[-1][1]["retrieval_warning"] == "未选择知识库"
    assert not any(name == "retrieval" for name, _ in events)


def test_stream_uses_history_rounds(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """历史对话轮数生效：第二轮请求会带上上一轮问答。"""
    session = client.post("/api/chat/sessions", headers=auth_headers, json={"history_rounds": 2}).json()["data"]
    client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={"session_id": session["id"], "question": "第一个问题"},
    )
    client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={"session_id": session["id"], "question": "第二个问题"},
    )

    messages = fake_llm.last_messages()
    contents = [message["content"] for message in messages]
    assert "第一个问题" in contents
    assert contents[-1] == "第二个问题"


def test_stream_first_question_sets_session_name(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """首轮提问后用问题内容自动命名会话。"""
    session = client.post("/api/chat/sessions", headers=auth_headers, json={}).json()["data"]
    client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={"session_id": session["id"], "question": "保修期是多久"},
    )
    sessions = client.get("/api/chat/sessions", headers=auth_headers).json()["data"]
    target = next(item for item in sessions if item["id"] == session["id"])
    assert target["name"] == "保修期是多久"


def test_stream_unknown_session_returns_404(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """会话不存在时返回 404。"""
    response = client.post("/api/chat/stream", headers=auth_headers, json={"session_id": 99999, "question": "你好"})
    assert response.status_code == 404


def test_stream_rejects_unsupported_model(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """流式问答传入未配置的模型返回 400。"""
    session = client.post("/api/chat/sessions", headers=auth_headers, json={}).json()["data"]
    response = client.post(
        "/api/chat/stream",
        headers=auth_headers,
        json={"session_id": session["id"], "question": "保修期", "model": "qwen-max"},
    )
    assert response.status_code == 400
    assert "不支持的大模型" in response.json()["message"]


def test_stream_rejects_empty_question(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """空问题返回 422。"""
    session = client.post("/api/chat/sessions", headers=auth_headers, json={}).json()["data"]
    response = client.post("/api/chat/stream", headers=auth_headers, json={"session_id": session["id"], "question": "  "})
    assert response.status_code == 422


def test_stream_without_api_key(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    """未配置 API Key 时返回 error 事件提示。"""
    import app.services.chat_service as chat_service_module

    class NotConfiguredLLM(FakeLLM):
        """模拟未配置 API Key 的大模型客户端。"""

        @property
        def configured(self) -> bool:  # noqa: D102
            return False

    monkeypatch.setattr(chat_service_module, "get_llm", lambda cfg=None: NotConfiguredLLM())
    session = client.post("/api/chat/sessions", headers=auth_headers, json={}).json()["data"]
    response = client.post(
        "/api/chat/stream", headers=auth_headers, json={"session_id": session["id"], "question": "保修期"}
    )
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert "API Key" in events[-1][1]["message"]


def test_other_user_cannot_read_session(client: TestClient, auth_headers: dict[str, str]) -> None:
    """其他用户无法读取他人会话。"""
    from tests.conftest import login_user, register_user

    session = client.post("/api/chat/sessions", headers=auth_headers, json={"name": "私有会话"}).json()["data"]
    register_user(client, username="other03")
    other_headers = {"Authorization": f"Bearer {login_user(client, username='other03')}"}

    assert client.get(f"/api/chat/sessions/{session['id']}/messages", headers=other_headers).status_code == 404
    assert client.delete(f"/api/chat/sessions/{session['id']}", headers=other_headers).status_code == 404


def test_session_unsupported_model_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    """不在配置中的模型名被拒绝。"""
    response = client.post("/api/chat/sessions", headers=auth_headers, json={"model": "qwen-max"})
    assert response.status_code == 400
    assert "不支持的大模型" in response.json()["message"]


def test_health_endpoint(client: TestClient) -> None:
    """健康检查返回各组件状态。"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mysql"] == "ok"
    assert data["milvus"] == "memory"
    assert data["llm_provider"] == "deepseek"
    assert data["llm_model"] == "deepseek-chat"
    assert "llm_configured" in data
