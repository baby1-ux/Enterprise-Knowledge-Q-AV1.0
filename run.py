"""本地启动脚本：python run.py

等价于：uvicorn app.main:app --app-dir backend --reload
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    """读取配置并启动服务。"""
    cfg = get_settings()
    uvicorn.run(
        "app.main:app",
        host=cfg.app.host,
        port=cfg.app.port,
        reload=cfg.app.debug,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
