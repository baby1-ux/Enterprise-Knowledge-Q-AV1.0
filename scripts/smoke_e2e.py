"""端到端冒烟测试（真实 DashScope 向量化 + 真实 DeepSeek 对话）。

不依赖 MySQL / Milvus：使用 SQLite + 内存向量库，验证完整 RAG 链路：
注册 → 登录 → 建知识库 → 上传文档 → 解析切块入库 → 向量检索 → 流式回答 → 引用来源

运行：.venv\\Scripts\\python.exe scripts/smoke_e2e.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import load_settings, override_settings  # noqa: E402
from app.db.session import dispose_engine, init_db, init_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.embedding import reset_embedder  # noqa: E402
from app.services.llm import reset_llm  # noqa: E402
from app.services.retriever import reset_retriever  # noqa: E402
from app.services.vector_store import reset_vector_store  # noqa: E402

SMOKE_DIR = PROJECT_ROOT / "data" / "smoke"
SAMPLE = PROJECT_ROOT / "data" / "samples" / "产品保修政策.md"


def build_settings():
    """构造冒烟测试配置：真实模型 + SQLite + 内存向量库。"""
    cfg = load_settings(PROJECT_ROOT / "config.yaml")
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.mysql.url_override = f"sqlite:///{(SMOKE_DIR / 'smoke.db').as_posix()}"
    cfg.milvus.provider = "memory"
    cfg.app.upload_dir = str(SMOKE_DIR / "uploads")
    cfg.app.log_dir = str(PROJECT_ROOT / "logs")
    cfg.app.secret_key = "smoke-test-secret-key-0123456789abcdef"
    cfg.captcha.debug_expose = True
    cfg.rag.retrieval.mode = "hybrid"
    cfg.rag.retrieval.top_k = 3
    return cfg


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """解析 SSE 文本。"""
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name, data = "", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data += line[len("data:") :].strip()
        if name:
            events.append((name, json.loads(data or "{}")))
    return events


def main() -> int:
    cfg = build_settings()
    override_settings(cfg)
    reset_embedder()
    reset_vector_store()
    reset_llm()
    reset_retriever()
    init_engine(cfg, force=True)
    init_db(cfg)

    app = create_app(cfg)
    steps: list[str] = []

    with TestClient(app) as client:
        # 1. 健康检查
        health = client.get("/api/health").json()["data"]
        print(f"[health] mysql={health['mysql']} milvus={health['milvus']} llm={health['llm_model']} "
              f"llm_key={health['llm_configured']} embedding_key={health['embedding_configured']}")
        steps.append("健康检查")

        # 2. 注册 + 登录
        captcha = client.get("/api/auth/captcha").json()["data"]
        register = client.post(
            "/api/auth/register",
            json={
                "username": "smoke_user",
                "password": "abc12345",
                "confirm_password": "abc12345",
                "captcha_id": captcha["captcha_id"],
                "captcha_code": captcha["code"],
            },
        ).json()
        if register["code"] != 0:
            print(f"[FAIL] 注册失败：{register['message']}")
            return 1
        captcha = client.get("/api/auth/captcha").json()["data"]
        login = client.post(
            "/api/auth/login",
            json={
                "username": "smoke_user",
                "password": "abc12345",
                "captcha_id": captcha["captcha_id"],
                "captcha_code": captcha["code"],
            },
        ).json()
        assert login["code"] == 0, login
        headers = {"Authorization": f"Bearer {login['data']['access_token']}"}
        steps.append("注册登录")

        # 3. 建知识库
        kb = client.post("/api/kb/", headers=headers, json={"name": "冒烟测试知识库", "description": "端到端验证"}).json()["data"]
        steps.append(f"建库(kb_id={kb['id']})")

        # 4. 上传并解析（后台任务在 TestClient 中同步执行）
        upload = client.post(
            f"/api/kb/{kb['id']}/documents",
            headers=headers,
            files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/markdown")},
            data={"chunk_size": "300", "chunk_overlap": "50", "retrieval_mode": "hybrid"},
        ).json()
        assert upload["code"] == 0, upload
        doc_id = upload["data"]["id"]

        status_data = client.get(f"/api/kb/documents/{doc_id}/status", headers=headers).json()["data"]
        print(f"[ingest] status={status_data['status']} chunks={status_data['chunk_count']} err={status_data['error_message']}")
        if status_data["status"] != "success":
            print("[FAIL] 文档解析失败")
            return 1
        steps.append(f"解析入库({status_data['chunk_count']} 块)")

        chunks = client.get(f"/api/kb/documents/{doc_id}/chunks?page=1&page_size=3", headers=headers).json()["data"]
        print(f"[chunks] total={chunks['total']}，首块前 40 字：{chunks['items'][0]['content'][:40]}...")

        # 5. 多轮问答（第一轮 + 依赖历史对话的第二轮）
        session = client.post("/api/chat/sessions", headers=headers, json={"kb_ids": [kb["id"]], "history_rounds": 5}).json()["data"]
        question = "产品保修期是多久？延保怎么买？"
        response = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"session_id": session["id"], "question": question, "retrieval_mode": "hybrid"},
        )
        events = parse_sse(response.text)
        names = [name for name, _ in events]
        answer = "".join(data["content"] for name, data in events if name == "delta")
        citations = next((data["chunks"] for name, data in events if name == "retrieval"), [])
        done = next((data for name, data in events if name == "done"), {})
        error = next((data for name, data in events if name == "error"), None)

        print(f"[stream] 事件顺序={names[:3]}... 末事件={names[-1] if names else '无'} 增量段数={names.count('delta')}")
        if error:
            print(f"[FAIL] 回答失败：{error['message']}")
            return 1
        print(f"[answer] {answer.strip()[:220]}")
        print(f"[citations] 命中 {len(citations)} 条：")
        for item in citations[:3]:
            print(f"    [{item['index']}] {item['doc_name']} p{item['page_no']} score={item['score']} | {item['preview'][:40]}")
        steps.append(f"检索+流式回答({len(answer)} 字, 引用 {len(citations)} 条)")

        # 6. 第二轮：验证历史对话能力
        response2 = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"session_id": session["id"], "question": "那保修范围包含哪些情况？"},
        )
        events2 = parse_sse(response2.text)
        answer2 = "".join(data["content"] for name, data in events2 if name == "delta")
        print(f"[answer2] {answer2.strip()[:160]}")
        steps.append("多轮对话")

        # 7. 分块编辑 → 重新向量化 → 消息持久化
        first_chunk = chunks["items"][0]
        edit = client.put(
            f"/api/kb/chunks/{first_chunk['id']}",
            headers=headers,
            json={"content": first_chunk["content"] + "\n（人工补充：保修期内运费由公司承担。）"},
        ).json()
        assert edit["code"] == 0, edit
        messages = client.get(f"/api/chat/sessions/{session['id']}/messages", headers=headers).json()["data"]
        print(f"[messages] 持久化消息 {len(messages)} 条，角色={[m['role'] for m in messages]}")
        steps.append("分块编辑+消息持久化")

    dispose_engine()
    print("\n========== 冒烟结果 ==========")
    for index, step in enumerate(steps, start=1):
        print(f"  {index}. {step}")
    print("全部通过 [OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
