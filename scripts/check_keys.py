"""真实 Key 连通性自检：DashScope 向量化 + DeepSeek 对话（不写入任何数据）。

运行：.venv\\Scripts\\python.exe scripts/check_keys.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import is_placeholder_api_key, load_settings  # noqa: E402
from app.services.embedding import DashScopeEmbedder, EmbeddingError  # noqa: E402
from app.services.llm import LLMClient, LLMError  # noqa: E402


def main() -> int:
    cfg = load_settings(PROJECT_ROOT / "config.yaml")
    print(f"对话模型: {cfg.llm.default_model} | base_url={cfg.llm.base_url}")
    print(f"向量模型: {cfg.embedding.model} | base_url={cfg.embedding.base_url}")
    print(
        f"llm.api_key 已配置: {not is_placeholder_api_key(cfg.llm.api_key)} | "
        f"embedding.api_key 已配置: {not is_placeholder_api_key(cfg.embedding.api_key)}"
    )

    failed = 0

    # ---------------- 1. 向量化 ----------------
    print("\n[1/2] 测试向量化 ...")
    try:
        embedder = DashScopeEmbedder(cfg)
        vectors = embedder.embed_documents(["产品保修期为一年。", "退货需要在 7 天内申请。"])
        query = embedder.embed_query("保修期多久")
        print(f"  [OK] 向量化成功：{len(vectors)} 条，维度={len(vectors[0])}，查询向量维度={len(query)}")
        print(f"     前 3 维 = {[round(value, 5) for value in vectors[0][:3]]}")
    except EmbeddingError as exc:
        print(f"  [FAIL] 向量化失败：{exc}")
        failed += 1

    # ---------------- 2. 对话 ----------------
    print("\n[2/2] 测试 DeepSeek 流式对话 ...")
    client = LLMClient(cfg)
    try:
        chunks: list[str] = []
        for delta in client.stream_chat(
            [
                {"role": "system", "content": "你是企业知识库助手，回答简洁。"},
                {"role": "user", "content": "用一句话说明什么是 RAG。"},
            ],
            max_tokens=256,
            temperature=0.3,
        ):
            chunks.append(delta)
        answer = "".join(chunks).strip()
        print(f"  [OK] 对话成功（流式 {len(chunks)} 段）：{answer[:120]}")
    except LLMError as exc:
        print(f"  [FAIL] 对话失败：{exc}")
        failed += 1

    # ---------------- 3. 推理模型（可选） ----------------
    print("\n[附加] 测试 deepseek-reasoner（验证采样参数被省略） ...")
    try:
        chunks = []
        for delta in client.stream_chat(
            [{"role": "user", "content": "1+1 等于几？只回答数字。"}],
            model="deepseek-reasoner",
            max_tokens=256,
            temperature=0.9,
            top_p=0.9,
        ):
            chunks.append(delta)
        print(f"  [OK] 推理模型成功：{''.join(chunks).strip()[:80]}")
    except LLMError as exc:
        print(f"  [WARN] 推理模型调用失败（不影响主流程）：{exc}")

    print("\n结果：" + ("全部通过 [OK]" if failed == 0 else f"{failed} 项失败 [FAIL]"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

