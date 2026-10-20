"""集成测试（默认跳过）：需要真实 MySQL / Milvus / DeepSeek + DashScope API Key。

启用方式：
    $env:RAG_E2E = "1"; python -m pytest tests/test_integration_e2e.py -v

说明：对话模型为 DeepSeek（deepseek-chat），向量化与 OCR 仍使用 DashScope，
因此需要同时配置 DEEPSEEK_API_KEY 与 DASHSCOPE_API_KEY。

未开启 RAG_E2E 时，本文件内的用例全部 skip，保证离线环境下 `pytest tests/` 全绿。
"""

from __future__ import annotations

import json
import os
import time

import pytest

pytestmark = [pytest.mark.integration]

E2E_ENABLED = os.getenv("RAG_E2E") == "1"
skip_reason = "未开启集成测试（设置环境变量 RAG_E2E=1 且已启动 MySQL / Milvus 并配置 API Key 后运行）"


@pytest.fixture()
def real_client():
    """使用 config.yaml 真实配置的客户端。"""
    if not E2E_ENABLED:
        pytest.skip(skip_reason)

    from fastapi.testclient import TestClient

    from app.core.config import clear_settings_override, load_settings, override_settings
    from app.db.session import dispose_engine, init_db, init_engine
    from app.main import create_app

    cfg = load_settings()
    override_settings(cfg)
    init_engine(cfg, force=True)
    init_db(cfg)
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client, cfg
    dispose_engine()
    clear_settings_override()


def _register_and_login(client, username: str) -> dict:
    """注册并登录，返回鉴权头。"""
    captcha = client.get("/api/auth/captcha").json()["data"]
    code = captcha.get("code")
    if not code:
        pytest.skip("config.yaml 中 captcha.debug_expose=false，集成测试无法自动读取验证码")

    payload = {
        "username": username,
        "password": "abc12345",
        "confirm_password": "abc12345",
        "captcha_id": captcha["captcha_id"],
        "captcha_code": code,
    }
    client.post("/api/auth/register", json=payload)

    captcha = client.get("/api/auth/captcha").json()["data"]
    login = client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": "abc12345",
            "captcha_id": captcha["captcha_id"],
            "captcha_code": captcha["code"],
        },
    ).json()
    assert login["code"] == 0, login
    return {"Authorization": f"Bearer {login['data']['access_token']}"}


def test_health_components(real_client) -> None:
    """MySQL / Milvus / 大模型配置均可用。"""
    client, _ = real_client
    data = client.get("/api/health").json()["data"]
    assert data["mysql"] == "ok", data
    assert data["milvus"] == "ok", data
    assert data["llm_configured"] is True, data


def test_full_rag_flow(real_client) -> None:
    """真实链路：建库 → 上传 → 解析入库 → 检索问答（流式）。"""
    client, cfg = real_client
    headers = _register_and_login(client, f"e2e{int(time.time())}")

    kb = client.post("/api/kb/", headers=headers, json={"name": "集成测试知识库"}).json()["data"]
    sample = cfg.project_root / "data" / "samples" / "产品保修政策.md"
    if not sample.exists():
        pytest.skip("缺少样例文档 data/samples/产品保修政策.md")

    upload = client.post(
        f"/api/kb/{kb['id']}/documents",
        headers=headers,
        files={"file": (sample.name, sample.read_bytes(), "text/markdown")},
        data={"chunk_size": "300", "chunk_overlap": "50", "retrieval_mode": "hybrid"},
    ).json()["data"]

    # 轮询解析状态
    status = ""
    for _ in range(60):
        status = client.get(f"/api/kb/documents/{upload['id']}/status", headers=headers).json()["data"]["status"]
        if status in ("success", "failed"):
            break
        time.sleep(1)
    assert status == "success", status

    session = client.post("/api/chat/sessions", headers=headers, json={"kb_ids": [kb["id"]]}).json()["data"]
    response = client.post(
        "/api/chat/stream",
        headers=headers,
        json={"session_id": session["id"], "question": "产品保修期是多久？", "retrieval_mode": "hybrid"},
    )
    events = []
    for block in response.text.split("\n\n"):
        if not block.strip():
            continue
        name, data = "", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if name:
            events.append((name, json.loads(data or "{}")))

    assert events[0][0] == "start"
    assert events[-1][0] == "done"
    assert events[-1][1]["answer"], "回答不能为空"
