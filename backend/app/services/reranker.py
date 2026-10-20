"""检索结果重排（Rerank）：DashScope gte-rerank / 本地 BGE Reranker。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

import requests

from ..core.config import Settings, is_placeholder_api_key, settings as current_settings
from ..core.logging import get_logger

logger = get_logger("reranker")


class RerankError(Exception):
    """重排失败。"""


class BaseReranker(ABC):
    """重排器基类。"""

    provider: str = ""
    model: str = ""

    @abstractmethod
    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        """返回 (原始下标, 相关性分数) 列表，按分数从高到低。"""


class NoopReranker(BaseReranker):
    """不重排：保持原顺序与分数。"""

    provider = "noop"
    model = "none"

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        return [(index, float(len(documents) - index)) for index in range(min(top_n, len(documents)))]


class DashScopeReranker(BaseReranker):
    """调用 DashScope 文本重排模型。"""

    provider = "dashscope"

    def __init__(self, cfg: Settings) -> None:
        self.api_key = cfg.rerank.api_key
        self.model = cfg.rerank.model
        self.base_url = (cfg.rerank.base_url or cfg.embedding.base_url).rstrip("/")
        self.timeout = cfg.rerank.timeout

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        if is_placeholder_api_key(self.api_key):
            raise RerankError("未配置 DashScope API Key，无法进行重排（config.yaml -> rerank.api_key）")

        url = f"{self.base_url}/services/rerank/text-rerank/text-rerank"
        payload = {
            "model": self.model,
            "input": {"query": query, "documents": list(documents)},
            "parameters": {"top_n": max(1, int(top_n)), "return_documents": False},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RerankError(f"请求重排服务失败：{exc}") from exc

        if response.status_code != 200:
            raise RerankError(f"重排服务返回 HTTP {response.status_code}：{response.text[:200]}")

        results = ((response.json().get("output") or {}).get("results")) or []
        pairs = [(int(item.get("index", 0)), float(item.get("relevance_score", 0.0))) for item in results]
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs


class LocalBGReranker(BaseReranker):  # noqa: N801 - 保持命名与配置一致
    """本地 BGE Reranker（需安装 sentence-transformers 并下载模型）。"""

    provider = "local_bge"

    def __init__(self, cfg: Settings) -> None:
        self.model = cfg.rerank.model_path
        self.model_path = str(cfg.resolve_path(cfg.rerank.model_path))
        self._encoder = None

    def _load(self):  # pragma: no cover - 依赖本地模型文件
        if self._encoder is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RerankError("本地重排模型未安装，请执行 pip install -e .[local-models]") from exc
            logger.info("正在加载本地重排模型：%s", self.model_path)
            self._encoder = CrossEncoder(self.model_path)
        return self._encoder

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        encoder = self._load()
        scores = encoder.predict([(query, document) for document in documents])
        pairs = [(index, float(score)) for index, score in enumerate(scores)]
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs[: max(1, int(top_n))]


def get_reranker(cfg: Settings | None = None) -> BaseReranker | None:
    """按配置获取重排器；未开启时返回 None。"""
    cfg = cfg or current_settings()
    if not cfg.rerank.enabled:
        return None
    provider = (cfg.rerank.provider or "dashscope").lower()
    if provider in ("local_bge", "local", "bge"):
        return LocalBGReranker(cfg)
    if provider in ("none", "noop", "off"):
        return None
    return DashScopeReranker(cfg)
