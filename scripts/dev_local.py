"""本地演示模式启动脚本：不依赖 MySQL / Milvus。

- 业务数据：SQLite（data/local/local.db）
- 向量库：内存实现（memory，进程重启后需重新解析文档）
- 大模型与向量化：真实调用 DeepSeek + DashScope（读取 config.yaml / .env）

适用场景：没有 Docker / MySQL / Milvus，但想快速演示前后端交互。

运行：.venv\\Scripts\\python.exe scripts/dev_local.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import load_settings, override_settings  # noqa: E402
from app.db.session import init_db, init_engine  # noqa: E402


def main() -> None:
    cfg = load_settings(PROJECT_ROOT / "config.yaml")
    local_dir = PROJECT_ROOT / "data" / "local"
    local_dir.mkdir(parents=True, exist_ok=True)

    cfg.mysql.url_override = f"sqlite:///{(local_dir / 'local.db').as_posix()}"
    cfg.milvus.provider = "memory"
    cfg.app.upload_dir = str(local_dir / "uploads")
    cfg.app.debug = False
    cfg.rag.retrieval.mode = "hybrid"
    # 仅本地演示：可用环境变量暴露验证码明文，便于脚本化自检（生产请勿开启）
    if os.getenv("RAG_DEMO_EXPOSE_CAPTCHA") == "1":
        cfg.captcha.debug_expose = True
    override_settings(cfg)

    init_engine(cfg, force=True)
    init_db(cfg)

    print("=" * 62)
    print("本地演示模式（SQLite + 内存向量库）")
    print(f"  对话模型  : {cfg.llm.default_model}  ({cfg.llm.base_url})")
    print(f"  向量模型  : {cfg.embedding.model}  ({cfg.embedding.base_url})")
    print(f"  数据文件  : {local_dir / 'local.db'}")
    print(f"  接口文档  : http://127.0.0.1:{cfg.app.port}/docs")
    print("  提示：内存向量库在进程重启后清空，需要重新上传文档")
    print("=" * 62)

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=cfg.app.port,
        reload=False,
        app_dir=str(PROJECT_ROOT / "backend"),
    )


if __name__ == "__main__":
    main()
