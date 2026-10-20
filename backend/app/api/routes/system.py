"""系统接口：健康检查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.config import Settings, is_placeholder_api_key
from ...core.logging import get_logger
from ...db.session import healthcheck as db_healthcheck
from ...services.vector_store import VectorStoreError, get_vector_store
from ..deps import get_settings_dep
from ..helpers import ok

router = APIRouter(tags=["系统"])
logger = get_logger("api.system")

_NO_KEY_PROVIDERS = ("hash", "offline", "memory", "local", "local_bge_m3", "bge_m3")


@router.get("/health", summary="健康检查")
def health(cfg: Settings = Depends(get_settings_dep)) -> dict:
    """返回 MySQL、Milvus、对话模型与向量化服务的可用状态。"""
    db_status = db_healthcheck(cfg)

    if (cfg.milvus.provider or "milvus").lower() in ("memory", "in-memory", "local"):
        milvus_status = "memory"
    else:
        try:
            milvus_status = get_vector_store(cfg).health()
        except VectorStoreError as exc:
            logger.warning("向量库健康检查失败：%s", exc)
            milvus_status = "error"

    embedding_provider = (cfg.embedding.provider or "dashscope").lower()
    embedding_configured = (
        True if embedding_provider in _NO_KEY_PROVIDERS else not is_placeholder_api_key(cfg.embedding.api_key)
    )

    return ok(
        {
            "status": "ok",
            "app": cfg.app.name,
            "version": cfg.app.version,
            "mysql": db_status,
            "milvus": milvus_status,
            "llm_provider": cfg.llm.provider,
            "llm_model": cfg.llm.default_model,
            "llm_configured": not is_placeholder_api_key(cfg.llm.api_key),
            "embedding": cfg.embedding.provider,
            "embedding_configured": embedding_configured,
        }
    )
