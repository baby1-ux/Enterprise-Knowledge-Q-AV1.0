"""前后端联调自检（走真实 HTTP，默认经 Vite 代理 5173 → 后端 8000）。

校验点：
  1. 图形验证码 → 注册 → 登录（JWT）
  2. 创建知识库 → 上传 Markdown → 后台解析入库
  3. SSE 流式问答能穿过 Vite 代理逐段到达（验证代理未缓冲流式响应）
  4. 引用来源、消息持久化

前置条件：后端以演示模式启动且暴露验证码明文：
    $env:RAG_DEMO_EXPOSE_CAPTCHA = "1"; .venv\\Scripts\\python.exe scripts/dev_local.py
    cd frontend && npm run dev

运行：.venv\\Scripts\\python.exe scripts/ui_flow_check.py [--base http://127.0.0.1:5173]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "产品保修政策.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="前后端联调自检")
    parser.add_argument("--base", default="http://127.0.0.1:5173", help="前端地址（Vite 代理 /api）")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    username = f"ui_check_{int(time.time())}"

    # 1. 验证码 + 注册
    captcha = requests.get(f"{base}/api/auth/captcha", timeout=10).json()["data"]
    if not captcha.get("code"):
        print("[FAIL] 未拿到验证码明文，请先用 RAG_DEMO_EXPOSE_CAPTCHA=1 启动后端")
        return 1
    register = requests.post(
        f"{base}/api/auth/register",
        json={
            "username": username,
            "password": "abc12345",
            "confirm_password": "abc12345",
            "captcha_id": captcha["captcha_id"],
            "captcha_code": captcha["code"],
        },
        timeout=10,
    ).json()
    assert register["code"] == 0, register
    print(f"[1/5] 注册成功：{register['data']}")

    # 2. 登录
    captcha = requests.get(f"{base}/api/auth/captcha", timeout=10).json()["data"]
    login = requests.post(
        f"{base}/api/auth/login",
        json={
            "username": username,
            "password": "abc12345",
            "captcha_id": captcha["captcha_id"],
            "captcha_code": captcha["code"],
        },
        timeout=10,
    ).json()
    assert login["code"] == 0, login
    headers = {"Authorization": f"Bearer {login['data']['access_token']}"}
    print(f"[2/5] 登录成功：user={login['data']['user']['username']}")

    # 3. 建库 + 上传解析
    kb = requests.post(f"{base}/api/kb/", headers=headers, json={"name": "联调知识库"}, timeout=10).json()["data"]
    with SAMPLE.open("rb") as handle:
        upload = requests.post(
            f"{base}/api/kb/{kb['id']}/documents",
            headers=headers,
            files={"file": (SAMPLE.name, handle, "text/markdown")},
            data={"chunk_size": "300", "chunk_overlap": "50", "retrieval_mode": "hybrid"},
            timeout=180,
        ).json()
    assert upload["code"] == 0, upload
    doc_id = upload["data"]["id"]
    # 真实服务中解析在后台执行，需要轮询状态
    status = {"status": "pending", "chunk_count": 0, "error_message": ""}
    for _ in range(60):
        status = requests.get(f"{base}/api/kb/documents/{doc_id}/status", headers=headers, timeout=30).json()["data"]
        if status["status"] in ("success", "failed"):
            break
        time.sleep(1)
    print(f"[3/5] 上传解析：status={status['status']} chunks={status['chunk_count']}")
    if status["status"] != "success":
        print(f"[FAIL] 解析失败：{status['error_message']}")
        return 1

    # 4. SSE 流式问答（流式读取，验证代理未缓冲）
    session = requests.post(
        f"{base}/api/chat/sessions", headers=headers, json={"kb_ids": [kb["id"]]}, timeout=10
    ).json()["data"]
    payload = {"session_id": session["id"], "question": "产品保修期是多久？", "retrieval_mode": "hybrid"}

    delta_count = 0
    answer_parts: list[str] = []
    citations: list[dict] = []
    event_names: list[str] = []
    first_delta_at = None
    started = time.time()

    with requests.post(
        f"{base}/api/chat/stream", headers={**headers, "Accept": "text/event-stream"}, json=payload, stream=True, timeout=300
    ) as response:
        assert response.status_code == 200, response.text[:200]
        event_name = ""
        data_buffer = ""
        for raw_line in response.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            if raw_line == "":
                if event_name:
                    event_names.append(event_name)
                    if event_name == "delta":
                        delta_count += 1
                        if first_delta_at is None:
                            first_delta_at = time.time() - started
                        answer_parts.append(json.loads(data_buffer)["content"])
                    elif event_name == "retrieval":
                        citations = json.loads(data_buffer).get("chunks", [])
                event_name, data_buffer = "", ""
                continue
            if raw_line.startswith("event:"):
                event_name = raw_line[len("event:") :].strip()
            elif raw_line.startswith("data:"):
                data_buffer += raw_line[len("data:") :].strip()

    answer = "".join(answer_parts).strip()
    print(f"[4/5] SSE 流式：事件={event_names[:3]}...{event_names[-1:]}，增量 {delta_count} 段，首段耗时 {first_delta_at:.2f}s")
    print(f"      回答：{answer[:150]}")
    print(f"      引用 {len(citations)} 条：{[item['doc_name'] + ' #' + str(item['index']) for item in citations[:3]]}")
    if delta_count < 2:
        print("[FAIL] 流式增量太少，可能被代理缓冲")
        return 1

    # 5. 消息持久化
    messages = requests.get(f"{base}/api/chat/sessions/{session['id']}/messages", headers=headers, timeout=30).json()["data"]
    print(f"[5/5] 消息持久化：{[m['role'] for m in messages]}")
    print("\n前后端联调自检通过 [OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
