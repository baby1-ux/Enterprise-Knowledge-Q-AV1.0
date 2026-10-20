"""系统接口：健康检查、用量统计。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ...core.config import Settings, is_placeholder_api_key
from ...core.logging import get_logger
from ...db.models import ChatMessage, ChatSession, Chunk, Document, KnowledgeBase, User
from ...db.session import get_db, healthcheck as db_healthcheck
from ...services.kb_service import KnowledgeBaseService
from ...services.vector_store import VectorStoreError, get_vector_store
from ..deps import get_current_user, get_kb_service, get_settings_dep
from ..helpers import ok

router = APIRouter(tags=["系统"])
# 统计接口挂在 /api/system 前缀下（健康检查保持 /api/health 不变）
system_router = APIRouter(prefix="/system", tags=["系统"])
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


@system_router.get("/stats", summary="用量统计")
def stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """统计当前用户可访问的知识库、文档、分块，以及自己的会话与消息数量（按用户隔离）。"""
    user_id = current_user.id

    # 知识库 / 文档 / 分块：按「可访问」口径（含被授权与公开的知识库）
    accessible_kb_ids = service.perm.accessible_kb_ids()
    kb_count = len(accessible_kb_ids)

    if accessible_kb_ids:
        doc_count = db.scalar(
            select(func.count(Document.id)).where(Document.kb_id.in_(accessible_kb_ids))
        ) or 0
        chunk_count = db.scalar(
            select(func.count(Chunk.id)).where(Chunk.kb_id.in_(accessible_kb_ids))
        ) or 0
    else:
        doc_count = 0
        chunk_count = 0

    session_count = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == user_id)) or 0

    message_stats = db.execute(
        select(
            func.count(ChatMessage.id),
            func.sum(case((ChatMessage.role == "assistant", 1), else_=0)),
        )
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
    ).one()

    message_count = int(message_stats[0] or 0)
    answer_count = int(message_stats[1] or 0)

    # 「今日回答」用数据库自身时钟界定“今天”（date(created_at) = date(now())），
    # 避免 SQLite（UTC）与 MySQL（服务器本地时间）的时区差异导致统计偏差
    today_answer_count = (
        db.scalar(
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.user_id == user_id,
                ChatMessage.role == "assistant",
                ChatMessage.content != "",
                func.date(ChatMessage.created_at) == func.date(func.now()),
            )
        )
        or 0
    )

    return ok(
        {
            "knowledge_base_count": int(kb_count),
            "document_count": int(doc_count),
            "chunk_count": int(chunk_count),
            "session_count": int(session_count),
            "message_count": message_count,
            "answer_count": answer_count,
            "today_answer_count": int(today_answer_count),
        }
    )
