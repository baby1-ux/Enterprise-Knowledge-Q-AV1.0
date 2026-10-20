"""检索器：把「问题」转成「候选分块列表」（向量化 → 向量检索 → 重排）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..core.config import Settings, settings as current_settings
from ..core.logging import get_logger
from .embedding import BaseEmbedder, EmbeddingError, get_embedder
from .reranker import BaseReranker, RerankError, get_reranker
from .vector_store import SearchHit, VectorStoreError, get_vector_store

logger = get_logger("retriever")


class RetrievalError(Exception):
    """检索失败。"""


@dataclass
class RetrievedChunk:
    """检索返回的分块。"""

    chunk_id: int
    doc_id: int
    kb_id: int
    content: str
    score: float = 0.0
    page_no: int | None = None

    def preview(self, length: int = 60) -> str:
        """用于前端展示的摘要。"""
        text = " ".join((self.content or "").split())
        return text if len(text) <= length else f"{text[:length]}…"


class Retriever:
    """RAG 检索器。"""

    def __init__(
        self,
        cfg: Settings | None = None,
        embedder: BaseEmbedder | None = None,
        vector_store=None,
        reranker: BaseReranker | None = None,
    ) -> None:
        self.settings = cfg or current_settings()
        self.embedder = embedder or get_embedder(self.settings)
        self.vector_store = vector_store if vector_store is not None else get_vector_store(self.settings)
        self.reranker = reranker

    # ------------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        kb_ids: Sequence[int],
        top_k: int | None = None,
        mode: str | None = None,
        alpha: float | None = None,
        score_threshold: float | None = None,
        use_rerank: bool | None = None,
    ) -> list[RetrievedChunk]:
        """检索与问题最相关的分块。"""
        query = (query or "").strip()
        kb_list = [int(kb_id) for kb_id in (kb_ids or [])]
        if not query or not kb_list:
            logger.info("跳过检索：问题为空或未选择知识库（kb_ids=%s）", kb_list)
            return []

        retrieval_cfg = self.settings.rag.retrieval
        top_k = int(top_k or retrieval_cfg.top_k)
        mode = (mode or retrieval_cfg.mode or "hybrid").lower()
        alpha = float(retrieval_cfg.hybrid_alpha if alpha is None else alpha)
        threshold = float(retrieval_cfg.score_threshold if score_threshold is None else score_threshold)
        candidate_k = max(top_k, top_k * max(1, retrieval_cfg.candidate_multiplier))

        try:
            query_vector = self.embedder.embed_query(query)
        except EmbeddingError as exc:
            raise RetrievalError(f"问题向量化失败：{exc}") from exc

        try:
            hits = self.vector_store.search(
                kb_ids=kb_list,
                query_text=query,
                query_vector=query_vector,
                top_k=candidate_k,
                mode=mode,
                alpha=alpha,
            )
        except VectorStoreError as exc:
            raise RetrievalError(f"向量检索失败：{exc}") from exc

        # 稠密检索的分数是余弦相似度，可直接按阈值过滤；混合检索分数为归一化融合分，不做阈值过滤
        if mode == "dense":
            filtered = [hit for hit in hits if hit.score >= threshold]
            if filtered:
                hits = filtered

        if not hits:
            logger.info("检索未命中：query=%s, kb_ids=%s", query[:50], kb_list)
            return []

        reranker = self.reranker if use_rerank is None else (self.reranker if use_rerank else None)
        if reranker is not None and len(hits) > 1:
            hits = self._rerank(query, hits, top_k)

        selected = hits[:top_k]
        logger.info(
            "检索完成：query=%s, 模式=%s, 候选=%s, 返回=%s, 最高分=%.4f",
            query[:50],
            mode,
            len(hits),
            len(selected),
            selected[0].score if selected else 0.0,
        )
        return [
            RetrievedChunk(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                kb_id=hit.kb_id,
                content=hit.content,
                score=float(hit.score),
                page_no=hit.page_no,
            )
            for hit in selected
        ]

    # ------------------------------------------------------------------
    def _rerank(self, query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
        """调用重排模型重新排序，失败时退回原顺序。"""
        try:
            pairs = self.reranker.rerank(query, [hit.content for hit in hits], top_n=top_k)  # type: ignore[union-attr]
        except RerankError as exc:
            logger.warning("重排失败，使用原始检索顺序：%s", exc)
            return hits

        reordered: list[SearchHit] = []
        for index, score in pairs:
            if 0 <= index < len(hits):
                hit = hits[index]
                hit.score = float(score)
                reordered.append(hit)
        return reordered or hits


_RETRIEVER_CACHE_KEY: dict[str, Retriever] = {}


def get_retriever(cfg: Settings | None = None) -> Retriever:
    """获取检索器（按配置缓存）。"""
    cfg = cfg or current_settings()
    key = f"{cfg.embedding.provider}:{cfg.milvus.provider}:{cfg.milvus.collection}:{cfg.rerank.enabled}"
    if key not in _RETRIEVER_CACHE_KEY:
        _RETRIEVER_CACHE_KEY[key] = Retriever(cfg, reranker=get_reranker(cfg))
    return _RETRIEVER_CACHE_KEY[key]


def reset_retriever() -> None:
    """清空检索器缓存（测试用）。"""
    _RETRIEVER_CACHE_KEY.clear()
