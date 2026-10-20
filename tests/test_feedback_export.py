"""消息反馈与对话导出测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeLLM, create_kb, upload_markdown, SAMPLE_MARKDOWN


def _ask_once(client: TestClient, headers: dict[str, str], question: str = "产品保修期是多久？") -> tuple[int, int]:
    """创建会话并提问一次，返回 (session_id, assistant_message_id)。"""
    kb = create_kb(client, headers)
    upload_markdown(client, headers, kb["id"], SAMPLE_MARKDOWN, chunk_size=150, chunk_overlap=20)
    session = client.post(
        "/api/chat/sessions", headers=headers, json={"kb_ids": [kb["id"]], "name": "保修咨询"}
    ).json()["data"]
    response = client.post(
        "/api/chat/stream",
        headers=headers,
        json={"session_id": session["id"], "question": question, "retrieval_mode": "dense"},
    )
    assert response.status_code == 200
    assert "event: done" in response.text

    messages = client.get(f"/api/chat/sessions/{session['id']}/messages", headers=headers).json()["data"]
    assistant = next(message for message in messages if message["role"] == "assistant")
    return session["id"], assistant["id"]


def test_feedback_like_persisted(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """点赞后接口返回且历史消息中保留 feedback=like。"""
    session_id, message_id = _ask_once(client, auth_headers)

    response = client.put(
        f"/api/chat/messages/{message_id}/feedback", headers=auth_headers, json={"feedback": "like"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["feedback"] == "like"

    messages = client.get(f"/api/chat/sessions/{session_id}/messages", headers=auth_headers).json()["data"]
    assistant = next(message for message in messages if message["role"] == "assistant")
    assert assistant["feedback"] == "like"


def test_feedback_dislike_then_cancel(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """点踩后可再取消（feedback 传 null）。"""
    _, message_id = _ask_once(client, auth_headers)

    dislike = client.put(
        f"/api/chat/messages/{message_id}/feedback", headers=auth_headers, json={"feedback": "dislike"}
    )
    assert dislike.json()["data"]["feedback"] == "dislike"

    cancel = client.put(
        f"/api/chat/messages/{message_id}/feedback", headers=auth_headers, json={"feedback": None}
    )
    assert cancel.status_code == 200
    assert cancel.json()["data"]["feedback"] is None


def test_feedback_rejects_user_message(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """只能对助手消息反馈，用户消息返回 400。"""
    session_id, _ = _ask_once(client, auth_headers)
    messages = client.get(f"/api/chat/sessions/{session_id}/messages", headers=auth_headers).json()["data"]
    user_message = next(message for message in messages if message["role"] == "user")

    response = client.put(
        f"/api/chat/messages/{user_message['id']}/feedback", headers=auth_headers, json={"feedback": "like"}
    )
    assert response.status_code == 400
    assert "助手" in response.json()["message"]


def test_feedback_rejects_invalid_value(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """非法反馈值返回 422。"""
    _, message_id = _ask_once(client, auth_headers)
    response = client.put(
        f"/api/chat/messages/{message_id}/feedback", headers=auth_headers, json={"feedback": "love"}
    )
    assert response.status_code == 422


def test_feedback_other_user_returns_404(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM
) -> None:
    """其他用户无法对他人消息反馈（返回 404，不暴露存在性）。"""
    from tests.conftest import login_user, register_user

    _, message_id = _ask_once(client, auth_headers)
    register_user(client, username="other_feedback")
    other_headers = {"Authorization": f"Bearer {login_user(client, username='other_feedback')}"}

    response = client.put(
        f"/api/chat/messages/{message_id}/feedback", headers=other_headers, json={"feedback": "like"}
    )
    assert response.status_code == 404


def test_feedback_requires_auth(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """未登录无法提交反馈（401）。"""
    _, message_id = _ask_once(client, auth_headers)
    response = client.put(f"/api/chat/messages/{message_id}/feedback", json={"feedback": "like"})
    assert response.status_code == 401


def test_export_session_markdown(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeLLM) -> None:
    """导出会话为 Markdown：包含问答内容、引用来源与模型参数。"""
    session_id, _ = _ask_once(client, auth_headers)

    response = client.get(f"/api/chat/sessions/{session_id}/export", headers=auth_headers)
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "attachment" in response.headers.get("content-disposition", "")

    text = response.text
    assert "产品保修期是多久？" in text  # 用户问题
    assert fake_llm.reply in text  # 助手回答
    assert "deepseek-chat" in text  # 模型信息
    assert "引用来源" in text  # 引用区域标题


def test_export_empty_session(client: TestClient, auth_headers: dict[str, str]) -> None:
    """空会话也可导出（仅包含会话信息）。"""
    session = client.post("/api/chat/sessions", headers=auth_headers, json={"name": "空会话"}).json()["data"]
    response = client.get(f"/api/chat/sessions/{session['id']}/export", headers=auth_headers)
    assert response.status_code == 200
    assert "空会话" in response.text


def test_export_other_user_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    """其他用户无法导出他人会话（404）。"""
    from tests.conftest import login_user, register_user

    session = client.post("/api/chat/sessions", headers=auth_headers, json={"name": "私有会话"}).json()["data"]
    register_user(client, username="other_export")
    other_headers = {"Authorization": f"Bearer {login_user(client, username='other_export')}"}

    response = client.get(f"/api/chat/sessions/{session['id']}/export", headers=other_headers)
    assert response.status_code == 404
