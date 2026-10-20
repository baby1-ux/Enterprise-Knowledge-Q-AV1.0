"""新功能端到端冒烟测试（真实 MySQL + Milvus + DeepSeek + DashScope）。

覆盖：注册/登录 → 统计 → 批量上传（含失败项）→ 跨库分块搜索 → 知识库名称搜索
     → 建会话 → 流式问答（真实大模型）→ 消息反馈 → 导出 Markdown
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "data" / "samples" / "产品保修政策.md"
SAMPLE2 = PROJECT_ROOT / "data" / "samples" / "售后服务规范.txt"


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def main() -> int:
    session = requests.Session()
    username = f"smoke_{int(time.time())}"

    # 1. 验证码 + 注册
    captcha = session.get(f"{BASE}/api/auth/captcha", timeout=10).json()["data"]
    register = session.post(
        f"{BASE}/api/auth/register",
        json={
            "username": username,
            "password": "abc12345",
            "confirm_password": "abc12345",
            "captcha_id": captcha["captcha_id"],
            "captcha_code": captcha["code"],
        },
        timeout=10,
    ).json()
    if register["code"] != 0:
        fail(f"注册失败：{register}")
    print(f"[1/9] 注册成功：{username}")

    # 2. 登录
    captcha = session.get(f"{BASE}/api/auth/captcha", timeout=10).json()["data"]
    login = session.post(
        f"{BASE}/api/auth/login",
        json={
            "username": username,
            "password": "abc12345",
            "captcha_id": captcha["captcha_id"],
            "captcha_code": captcha["code"],
        },
        timeout=10,
    ).json()
    if login["code"] != 0:
        fail(f"登录失败：{login}")
    headers = {"Authorization": f"Bearer {login['data']['access_token']}"}
    print("[2/9] 登录成功")

    # 3. 统计（空数据）
    stats = session.get(f"{BASE}/api/system/stats", headers=headers, timeout=10).json()["data"]
    if stats["knowledge_base_count"] != 0:
        fail(f"新用户统计应为 0：{stats}")
    print(f"[3/9] 统计接口正常（新用户全部为 0）")

    # 4. 批量上传：2 个合法文件 + 1 个非法文件
    kb = session.post(f"{BASE}/api/kb/", headers=headers, json={"name": "冒烟测试库"}, timeout=10).json()["data"]
    files = [
        ("files", (SAMPLE.name, SAMPLE.read_bytes(), "text/markdown")),
        ("files", (SAMPLE2.name, SAMPLE2.read_bytes(), "text/plain")),
        ("files", ("病毒.exe", b"MZ fake", "application/octet-stream")),
    ]
    batch = session.post(
        f"{BASE}/api/kb/{kb['id']}/documents/batch",
        headers=headers,
        files=files,
        data={"chunk_size": "300", "chunk_overlap": "50", "retrieval_mode": "hybrid"},
        timeout=120,
    ).json()["data"]
    if len(batch["uploaded"]) != 2 or len(batch["failed"]) != 1:
        fail(f"批量上传结果异常：{batch}")
    print(f"[4/9] 批量上传：成功 {len(batch['uploaded'])}，失败 {len(batch['failed'])}（{batch['failed'][0]['message']}）")

    # 5. 轮询解析状态
    doc_ids = [item["id"] for item in batch["uploaded"]]
    for _ in range(60):
        statuses = [
            session.get(f"{BASE}/api/kb/documents/{doc_id}/status", headers=headers, timeout=30).json()["data"]
            for doc_id in doc_ids
        ]
        if all(item["status"] in ("success", "failed") for item in statuses):
            break
        time.sleep(1)
    if not all(item["status"] == "success" for item in statuses):
        fail(f"解析失败：{statuses}")
    print(f"[5/9] 解析完成：{[item['chunk_count'] for item in statuses]} 个分块")

    # 6. 跨库分块搜索 + 知识库名称搜索
    search = session.get(
        f"{BASE}/api/kb/chunks/search", headers=headers, params={"keyword": "保修"}, timeout=10
    ).json()["data"]
    if search["total"] < 2:
        fail(f"跨库搜索命中不足：{search['total']}")
    print(f"[6/9] 跨库搜索「保修」命中 {search['total']} 条，首条来自「{search['items'][0]['doc_name']}」")

    kb_search = session.get(f"{BASE}/api/kb/", headers=headers, params={"keyword": "冒烟"}, timeout=10).json()["data"]
    if len(kb_search) != 1:
        fail(f"知识库名称搜索异常：{kb_search}")
    print(f"[7/9] 知识库名称搜索命中：{kb_search[0]['name']}")

    # 8. 建会话 + 流式问答（真实 DeepSeek）
    chat_session = session.post(
        f"{BASE}/api/chat/sessions", headers=headers, json={"kb_ids": [kb["id"]], "name": "冒烟会话"}, timeout=10
    ).json()["data"]

    delta_count = 0
    answer_parts: list[str] = []
    citations: list[dict] = []
    assistant_message_id = None
    with session.post(
        f"{BASE}/api/chat/stream",
        headers=headers,
        json={
            "session_id": chat_session["id"],
            "question": "产品保修期是多久？延保怎么买？",
            "retrieval_mode": "hybrid",
        },
        stream=True,
        timeout=180,
    ) as response:
        event_name = ""
        data_buffer = ""
        for raw_line in response.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            if raw_line == "":
                if event_name:
                    payload = json.loads(data_buffer or "{}")
                    if event_name == "start":
                        assistant_message_id = payload.get("assistant_message_id")
                    elif event_name == "delta":
                        delta_count += 1
                        answer_parts.append(payload.get("content", ""))
                    elif event_name == "retrieval":
                        citations = payload.get("chunks", [])
                    elif event_name == "error":
                        fail(f"流式问答报错：{payload}")
                event_name, data_buffer = "", ""
                continue
            if raw_line.startswith("event:"):
                event_name = raw_line[len("event:"):].strip()
            elif raw_line.startswith("data:"):
                data_buffer += raw_line[len("data:"):].strip()

    answer = "".join(answer_parts).strip()
    if delta_count < 2 or not answer:
        fail(f"流式输出异常：delta={delta_count}")
    print(f"[8/9] 流式问答：增量 {delta_count} 段，引用 {len(citations)} 条")
    print(f"      回答：{answer[:120]}")

    # 9. 反馈 + 导出
    if not assistant_message_id:
        fail("未拿到助手消息 id")
    feedback = session.put(
        f"{BASE}/api/chat/messages/{assistant_message_id}/feedback",
        headers=headers,
        json={"feedback": "like"},
        timeout=10,
    ).json()
    if feedback["data"]["feedback"] != "like":
        fail(f"反馈异常：{feedback}")
    print(f"[9/9] 消息反馈：like")

    export = session.get(
        f"{BASE}/api/chat/sessions/{chat_session['id']}/export", headers=headers, timeout=30
    )
    if export.status_code != 200 or "产品保修期是多久" not in export.text:
        fail(f"导出异常：HTTP {export.status_code}")
    print(f"      导出成功：{len(export.text)} 字符（含引用来源：{'引用来源' in export.text}）")

    # 统计复核
    stats = session.get(f"{BASE}/api/system/stats", headers=headers, timeout=10).json()["data"]
    print(f"      统计复核：{stats}")
    assert stats["knowledge_base_count"] == 1
    assert stats["document_count"] == 2
    assert stats["answer_count"] == 1
    assert stats["today_answer_count"] == 1

    print("\n新功能端到端冒烟测试全部通过 [OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
