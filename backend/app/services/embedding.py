"""文本向量化：DashScope 向量模型（默认）、本地 BGE-M3、离线哈希向量。

说明：对话模型已切换为 DeepSeek，但 DeepSeek 暂未提供向量化接口，
因此向量化默认仍使用 DashScope（text-embedding-v4），Key 独立配置在 embedding.api_key。
"""

from __future__ import annotations

import hashlib
import math
import time
from abc import ABC, abstractmethod
from typing import Sequence

import requests

from ..core.config import Settings, is_placeholder_api_key, settings as current_settings
from ..core.logging import get_logger

logger = get_logger("embedding")

# DashScope 单条文本上限约 8192 token，这里按字符保守截断
_MAX_CHARS = 4000


class EmbeddingError(Exception):
    """向量化失败。"""


class BaseEmbedder(ABC):
    """向量化器基类。"""

    provider: str = ""
    model: str = ""
    dimension: int = 0

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """批量向量化文档文本。"""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """向量化查询文本。"""

    def describe(self) -> str:
        """用于日志展示的描述。"""
        return f"{self.provider}:{self.model}(dim={self.dimension})"


class HashEmbedder(BaseEmbedder):
    """离线哈希向量化器：无需外部服务，用于本地演示与单元测试。"""

    provider = "hash"

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = max(16, int(dimension))
        self.model = f"hash-{self.dimension}"

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        cleaned = (text or "").strip()
        if not cleaned:
            return vector
        # 中文按 2-gram 切分，英文按单词切分，保证同类文本向量接近
        tokens = _tokenize(cleaned)
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _tokenize(text: str) -> list[str]:
    """中文 2-gram + 英文单词混合切分。"""
    tokens: list[str] = []
    buffer = ""
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if buffer:
                tokens.append(buffer.lower())
                buffer = ""
            tokens.append(char)
        elif char.isalnum():
            buffer += char
        else:
            if buffer:
                tokens.append(buffer.lower())
                buffer = ""
    if buffer:
        tokens.append(buffer.lower())

    # 中文单字扩展为 2-gram，提升语义区分度
    chinese = [token for token in tokens if len(token) == 1 and "\u4e00" <= token <= "\u9fff"]
    grams = [f"{chinese[i]}{chinese[i + 1]}" for i in range(len(chinese) - 1)]
    return tokens + grams


class DashScopeEmbedder(BaseEmbedder):
    """调用 DashScope 文本向量模型（默认 text-embedding-v4）。"""

    provider = "dashscope"

    def __init__(self, cfg: Settings) -> None:
        self.api_key = cfg.embedding.api_key
        self.model = cfg.embedding.model
        self.dimension = cfg.embedding.dimension
        self.batch_size = max(1, cfg.embedding.batch_size)
        self.timeout = cfg.embedding.timeout
        self.max_retries = max(1, cfg.embedding.max_retries)
        self.base_url = cfg.embedding.base_url.rstrip("/")

    # ------------------------------------------------------------------
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed_batch(list(texts), text_type="document")

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed_batch([text], text_type="query")
        if not vectors:
            raise EmbeddingError("向量化失败：返回结果为空")
        return vectors[0]

    # ------------------------------------------------------------------
    def _embed_batch(self, texts: list[str], text_type: str) -> list[list[float]]:
        if not texts:
            return []
        if is_placeholder_api_key(self.api_key):
            raise EmbeddingError(
                "未配置 DashScope API Key，无法进行向量化"
                "（config.yaml -> embedding.api_key，或环境变量 DASHSCOPE_API_KEY；"
                "也可把 embedding.provider 改为 hash / local_bge_m3）"
            )

        results: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [text[: _MAX_CHARS] if text else " " for text in texts[start : start + self.batch_size]]
            results.extend(self._call_with_retry(batch, text_type))
        return results

    def _call_with_retry(self, batch: list[str], text_type: str) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._call(batch, text_type)
            except EmbeddingError as exc:
                last_error = exc
                logger.warning("向量化调用失败（第 %s/%s 次）：%s", attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 * attempt, 5))
        raise EmbeddingError(f"向量化失败：{last_error}")

    def _call(self, batch: list[str], text_type: str) -> list[list[float]]:
        url = f"{self.base_url}/services/embeddings/text-embedding/text-embedding"
        payload = {
            "model": self.model,
            "input": {"texts": batch},
            "parameters": {"dimension": self.dimension, "text_type": text_type},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise EmbeddingError(f"请求 DashScope 失败：{exc}") from exc

        if response.status_code != 200:
            raise EmbeddingError(f"DashScope 返回 HTTP {response.status_code}：{response.text[:200]}")

        data = response.json()
        embeddings = (data.get("output") or {}).get("embeddings") or []
        if not embeddings:
            raise EmbeddingError(f"DashScope 未返回向量：{str(data)[:200]}")

        embeddings.sort(key=lambda item: item.get("text_index", 0))
        vectors = [list(map(float, item.get("embedding") or [])) for item in embeddings]
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(f"向量维度不一致：期望 {self.dimension}，实际 {len(vector)}")
        return vectors


class LocalBGEM3Embedder(BaseEmbedder):
    """本地 BGE-M3 向量化（需安装 sentence-transformers 并下载模型）。"""

    provider = "local_bge_m3"

    def __init__(self, cfg: Settings) -> None:
        self.model_path = str(cfg.resolve_path(cfg.embedding.model_path))
        self.model = cfg.embedding.model_path
        self.dimension = cfg.embedding.dimension
        self._model = None

    def _load(self):  # pragma: no cover - 依赖本地大模型文件
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "本地向量模型未安装，请执行 pip install -e .[local-models]，或把 embedding.provider 改为 dashscope"
                ) from exc
            logger.info("正在加载本地向量模型：%s", self.model_path)
            self._model = SentenceTransformer(self.model_path, device="cpu")
            self.dimension = int(self._model.get_sentence_embedding_dimension())
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(list(texts), normalize_embeddings=True, batch_size=8)
        return [list(map(float, vector)) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_EMBEDDER_CACHE: dict[str, BaseEmbedder] = {}


def build_embedder(cfg: Settings | None = None) -> BaseEmbedder:
    """按配置创建向量化器。"""
    cfg = cfg or current_settings()
    provider = (cfg.embedding.provider or "dashscope").lower()
    if provider in ("hash", "offline", "memory"):
        return HashEmbedder(cfg.embedding.dimension)
    if provider in ("local_bge_m3", "local", "bge_m3"):
        return LocalBGEM3Embedder(cfg)
    return DashScopeEmbedder(cfg)


def get_embedder(cfg: Settings | None = None) -> BaseEmbedder:
    """获取向量化器（按配置缓存）。"""
    cfg = cfg or current_settings()
    key = (
        f"{cfg.embedding.provider}:{cfg.embedding.model}:{cfg.embedding.dimension}:"
        f"{cfg.embedding.base_url}:{bool(cfg.embedding.api_key)}"
    )
    if key not in _EMBEDDER_CACHE:
        _EMBEDDER_CACHE[key] = build_embedder(cfg)
        logger.info("向量化器已初始化：%s", _EMBEDDER_CACHE[key].describe())
    return _EMBEDDER_CACHE[key]


def reset_embedder() -> None:
    """清空缓存（测试用）。"""
    _EMBEDDER_CACHE.clear()
