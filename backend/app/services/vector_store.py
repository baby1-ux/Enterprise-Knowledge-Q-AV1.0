"""向量库层：Milvus（稠密 + BM25 混合检索），并提供内存实现用于演示与单测。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Sequence

from ..core.config import Settings, settings as current_settings
from ..core.logging import get_logger

logger = get_logger("vector_store")

# Milvus VARCHAR 上限按字节计算，中文 1 字约 3 字节，保守截断
_MAX_CONTENT_CHARS = 4000


class VectorStoreError(Exception):
    """向量库操作失败。"""


@dataclass
class VectorRecord:
    """待写入向量库的分块记录。"""

    chunk_id: int
    kb_id: int
    doc_id: int
    content: str
    dense: list[float]
    page_no: int | None = None
    enabled: bool = True

    @property
    def pk(self) -> str:
        """Milvus 主键。"""
        return f"chunk-{self.chunk_id}"


@dataclass
class SearchHit:
    """检索命中结果。"""

    chunk_id: int
    doc_id: int
    kb_id: int
    content: str
    score: float = 0.0
    page_no: int | None = None
    meta: dict = field(default_factory=dict)


def _row_to_hit(row: dict, score: float) -> SearchHit:
    """Milvus 返回结果转 SearchHit。"""
    entity = row.get("entity") or row
    page_no = entity.get("page_no")
    return SearchHit(
        chunk_id=int(entity.get("chunk_id", 0) or 0),
        doc_id=int(entity.get("doc_id", 0) or 0),
        kb_id=int(entity.get("kb_id", 0) or 0),
        content=str(entity.get("content", "") or ""),
        score=float(score),
        page_no=int(page_no) if page_no not in (None, 0) else None,
    )


class MilvusVectorStore:
    """基于 Milvus 的向量库实现。"""

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.collection = cfg.milvus.collection
        self.metric_type = cfg.milvus.metric_type
        self.dimension = cfg.embedding.dimension
        self._client = None
        self._lock = threading.Lock()
        self._ready = False
        self._bm25_ready = True

    # ------------------------------------------------------------------ 连接
    @property
    def client(self):
        """惰性创建 Milvus 客户端。"""
        if self._client is None:
            self._connect()
        return self._client

    def _connect(self) -> None:
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:  # pragma: no cover
            raise VectorStoreError("缺少 pymilvus 依赖，无法连接 Milvus 向量库") from exc

        uri = self.cfg.milvus.uri
        token = ""
        if self.cfg.milvus.user:
            token = f"{self.cfg.milvus.user}:{self.cfg.milvus.password}"

        database = self.cfg.milvus.database
        try:  # 先确保数据库存在
            bootstrap = MilvusClient(uri=uri, token=token)
            try:
                databases = bootstrap.list_databases()
                if database not in databases:
                    bootstrap.create_database(database)
                    logger.info("已创建 Milvus 数据库：%s", database)
            finally:
                bootstrap.close()
        except Exception as exc:  # pragma: no cover - 依赖真实服务
            logger.warning("准备 Milvus 数据库失败，将尝试直接连接：%s", exc)

        try:
            self._client = MilvusClient(uri=uri, token=token, db_name=database)
            logger.info("已连接 Milvus：%s / 数据库=%s / 集合=%s", uri, database, self.collection)
        except Exception as exc:  # pragma: no cover
            raise VectorStoreError(f"连接 Milvus 失败（{uri}）：{exc}") from exc

    # ------------------------------------------------------------------ 集合
    def ensure_collection(self, dimension: int | None = None) -> None:
        """确保集合与索引存在，并校验向量维度与 BM25 函数一致性。"""
        dim = int(dimension or self.dimension)
        with self._lock:
            if self._ready:
                return
            client = self.client
            if client.has_collection(self.collection):
                existing = self._existing_dimension(client)
                if existing and existing != dim:
                    raise VectorStoreError(
                        f"向量集合 {self.collection} 的维度为 {existing}，与当前配置 {dim} 不一致，"
                        "请修改 config.yaml 中的 milvus.collection 名称或清空集合后重试"
                    )
                # 检测旧集合：存在 sparse 字段但缺少 BM25 函数，会导致 upsert 失败，
                # 直接删除并重建为稠密向量集合，避免旧数据阻塞后续写入。
                if self._has_sparse_field(client) and not self._has_bm25_function(client):
                    logger.warning(
                        "集合 %s 存在 sparse 字段但缺少 BM25 函数，将删除并重建为稠密向量集合",
                        self.collection,
                    )
                    try:
                        client.drop_collection(self.collection)
                    except Exception as drop_exc:  # noqa: BLE001
                        logger.warning("删除旧集合失败：%s", drop_exc)
                    self._create_collection(client, dim)
                else:
                    self._bm25_ready = self._has_bm25_function(client)
            else:
                self._create_collection(client, dim)
            self._ready = True
            self.dimension = dim

    def _existing_dimension(self, client) -> int | None:
        try:
            info = client.describe_collection(self.collection)
        except Exception as exc:  # pragma: no cover
            logger.warning("读取集合信息失败：%s", exc)
            return None
        for item in info.get("fields", []):
            if item.get("name") == "dense":
                params = item.get("params") or {}
                dimension = params.get("dim")
                return int(dimension) if dimension else None
        return None

    def _has_sparse_field(self, client) -> bool:
        try:
            info = client.describe_collection(self.collection)
        except Exception as exc:  # pragma: no cover
            logger.warning("读取集合信息失败：%s", exc)
            return False
        return any(item.get("name") == "sparse" for item in info.get("fields", []))

    def _has_bm25_function(self, client) -> bool:
        try:
            info = client.describe_collection(self.collection)
        except Exception as exc:  # pragma: no cover
            logger.warning("读取集合信息失败：%s", exc)
            return False
        return any(
            (item.get("name") == "content_bm25" or item.get("type") == "BM25")
            for item in info.get("functions", [])
        )

    def _create_collection(self, client, dimension: int) -> None:
        """创建集合：稠密向量 + BM25 稀疏向量（中文分析器）。"""
        try:
            self._do_create(client, dimension, with_sparse=True)
            # 部分 Milvus 版本/环境不会真正注册 BM25 函数，创建后需二次校验
            if not self._has_bm25_function(client):
                raise VectorStoreError("集合创建后未找到 BM25 函数，当前环境可能不支持 BM25")
            self._bm25_ready = True
            logger.info("已创建向量集合（稠密 + BM25 混合）：%s，维度=%s", self.collection, dimension)
        except Exception as exc:  # pragma: no cover - 依赖 Milvus 版本
            logger.warning("创建混合检索集合失败，降级为仅稠密向量：%s", exc)
            if client.has_collection(self.collection):
                try:
                    client.drop_collection(self.collection)
                except Exception:  # noqa: BLE001
                    pass
            self._do_create(client, dimension, with_sparse=False)
            self._bm25_ready = False
            logger.info("已创建向量集合（仅稠密）：%s，维度=%s", self.collection, dimension)

    def _do_create(self, client, dimension: int, with_sparse: bool) -> None:
        from pymilvus import DataType, Function, FunctionType

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64)
        schema.add_field(field_name="doc_id", datatype=DataType.INT64)
        schema.add_field(field_name="kb_id", datatype=DataType.INT64)
        schema.add_field(field_name="page_no", datatype=DataType.INT64)
        schema.add_field(field_name="enabled", datatype=DataType.BOOL)
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=16384,
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
        )
        schema.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=dimension)

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense",
            index_type=self.cfg.milvus.index_type,
            metric_type=self.metric_type,
            params={
                "M": self.cfg.milvus.hnsw_m,
                "efConstruction": self.cfg.milvus.hnsw_ef_construction,
            },
        )

        if with_sparse:
            schema.add_field(
                field_name="sparse",
                datatype=DataType.SPARSE_FLOAT_VECTOR,
                nullable=True,
            )
            schema.add_function(
                Function(
                    name="content_bm25",
                    function_type=FunctionType.BM25,
                    input_field_names=["content"],
                    output_field_names=["sparse"],
                )
            )
            index_params.add_index(
                field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="IP", params={}
            )

        client.create_collection(collection_name=self.collection, schema=schema, index_params=index_params)

    # ------------------------------------------------------------------ 写入
    def upsert(self, records: Sequence[VectorRecord]) -> int:
        """批量写入/更新向量，返回成功条数。"""
        if not records:
            return 0
        self.ensure_collection(len(records[0].dense))
        rows = [
            {
                "id": record.pk,
                "chunk_id": int(record.chunk_id),
                "doc_id": int(record.doc_id),
                "kb_id": int(record.kb_id),
                "page_no": int(record.page_no or 0),
                "enabled": bool(record.enabled),
                "content": (record.content or "")[:_MAX_CONTENT_CHARS],
                "dense": [float(value) for value in record.dense],
            }
            for record in records
        ]
        written = 0
        batch_size = 100
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            try:
                self.client.upsert(collection_name=self.collection, data=batch)
                written += len(batch)
            except Exception as exc:  # pragma: no cover
                raise VectorStoreError(f"写入向量库失败：{exc}") from exc
        logger.debug("向量写入完成：%s 条", written)
        return written

    # ------------------------------------------------------------------ 删除
    def delete_chunks(self, chunk_ids: Sequence[int]) -> None:
        ids = [f"chunk-{int(chunk_id)}" for chunk_id in chunk_ids]
        if not ids:
            return
        try:
            self.client.delete(collection_name=self.collection, ids=ids)
            logger.debug("已删除向量：%s 条", len(ids))
        except Exception as exc:  # pragma: no cover
            raise VectorStoreError(f"删除向量失败：{exc}") from exc

    def delete_by_documents(self, doc_ids: Sequence[int]) -> None:
        if not doc_ids:
            return
        expr = "doc_id in [" + ", ".join(str(int(doc_id)) for doc_id in doc_ids) + "]"
        self._delete_by_expr(expr)

    def delete_by_kb(self, kb_id: int) -> None:
        self._delete_by_expr(f"kb_id == {int(kb_id)}")

    def _delete_by_expr(self, expr: str) -> None:
        try:
            self.client.delete(collection_name=self.collection, filter=expr)
            logger.debug("按条件删除向量：%s", expr)
        except Exception as exc:  # pragma: no cover
            raise VectorStoreError(f"删除向量失败：{exc}") from exc

    # ------------------------------------------------------------------ 检索
    def search(
        self,
        kb_ids: Sequence[int],
        query_text: str,
        query_vector: list[float],
        top_k: int = 5,
        mode: str = "dense",
        alpha: float = 0.7,
    ) -> list[SearchHit]:
        """检索分块；混合检索失败时自动降级为稠密检索。"""
        if not kb_ids:
            return []
        self.ensure_collection(len(query_vector) if query_vector else None)
        expr = self._build_expr(kb_ids)
        limit = max(1, int(top_k))

        if mode == "hybrid" and self._bm25_ready:
            try:
                return self._hybrid_search(query_text, query_vector, limit, alpha, expr)
            except Exception as exc:  # pragma: no cover - 依赖 Milvus 版本
                logger.warning("混合检索失败，降级为稠密检索：%s", exc)
                self._bm25_ready = False
        return self._dense_search(query_vector, limit, expr)

    def _build_expr(self, kb_ids: Sequence[int]) -> str:
        ids = ", ".join(str(int(kb_id)) for kb_id in kb_ids)
        return f"kb_id in [{ids}] and enabled == true"

    def _dense_search(self, query_vector: list[float], limit: int, expr: str) -> list[SearchHit]:
        try:
            results = self.client.search(
                collection_name=self.collection,
                data=[query_vector],
                anns_field="dense",
                search_params={
                    "metric_type": self.metric_type,
                    "params": {"ef": self.cfg.milvus.search_ef},
                },
                limit=limit,
                filter=expr,
                output_fields=["chunk_id", "doc_id", "kb_id", "page_no", "content"],
            )
        except Exception as exc:  # pragma: no cover
            raise VectorStoreError(f"稠密检索失败：{exc}") from exc
        hits = results[0] if results else []
        return [_row_to_hit(row, row.get("distance", 0.0)) for row in hits]

    def _hybrid_search(
        self, query_text: str, query_vector: list[float], limit: int, alpha: float, expr: str
    ) -> list[SearchHit]:
        from pymilvus import AnnSearchRequest, WeightedRanker

        dense_request = AnnSearchRequest(
            data=[query_vector],
            anns_field="dense",
            param={"metric_type": self.metric_type, "params": {"ef": self.cfg.milvus.search_ef}},
            limit=limit,
            expr=expr,
        )
        sparse_request = AnnSearchRequest(
            data=[query_text],
            anns_field="sparse",
            param={"metric_type": "IP"},
            limit=limit,
            expr=expr,
        )
        results = self.client.hybrid_search(
            collection_name=self.collection,
            reqs=[dense_request, sparse_request],
            ranker=WeightedRanker(float(alpha), float(1 - alpha)),
            limit=limit,
            output_fields=["chunk_id", "doc_id", "kb_id", "page_no", "content"],
        )
        hits = results[0] if results else []
        return [_row_to_hit(row, row.get("distance", 0.0)) for row in hits]

    # ------------------------------------------------------------------ 其它
    def health(self) -> str:
        """连通性检查。"""
        try:
            self.client.get_load_state(self.collection) if self.client.has_collection(self.collection) else None
            return "ok"
        except Exception as exc:  # pragma: no cover
            logger.error("Milvus 健康检查失败：%s", exc)
            return "error"

    def count(self, kb_id: int | None = None) -> int:  # pragma: no cover - 便于运维排查
        """统计向量数量。"""
        try:
            if kb_id is None:
                stats = self.client.query(
                    collection_name=self.collection, filter="", output_fields=["count(*)"]
                )
            else:
                stats = self.client.query(
                    collection_name=self.collection,
                    filter=f"kb_id == {int(kb_id)}",
                    output_fields=["count(*)"],
                )
            return int(stats[0].get("count(*)", 0)) if stats else 0
        except Exception:
            return 0


class MemoryVectorStore:
    """内存向量库：无需部署，用于本地演示、单元测试与离线回归。"""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or current_settings()
        self._rows: dict[int, VectorRecord] = {}
        self._lock = threading.Lock()
        self.dimension = self.cfg.embedding.dimension

    def ensure_collection(self, dimension: int | None = None) -> None:
        if dimension:
            self.dimension = int(dimension)

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        with self._lock:
            for record in records:
                self._rows[int(record.chunk_id)] = record
        return len(records)

    def delete_chunks(self, chunk_ids: Sequence[int]) -> None:
        with self._lock:
            for chunk_id in chunk_ids:
                self._rows.pop(int(chunk_id), None)

    def delete_by_documents(self, doc_ids: Sequence[int]) -> None:
        targets = {int(doc_id) for doc_id in doc_ids}
        with self._lock:
            for key in [key for key, row in self._rows.items() if row.doc_id in targets]:
                self._rows.pop(key, None)

    def delete_by_kb(self, kb_id: int) -> None:
        with self._lock:
            for key in [key for key, row in self._rows.items() if row.kb_id == int(kb_id)]:
                self._rows.pop(key, None)

    def search(
        self,
        kb_ids: Sequence[int],
        query_text: str,
        query_vector: list[float],
        top_k: int = 5,
        mode: str = "dense",
        alpha: float = 0.7,
    ) -> list[SearchHit]:
        if not kb_ids:
            return []
        allowed = {int(kb_id) for kb_id in kb_ids}
        from .embedding import _tokenize

        query_tokens = set(_tokenize(query_text or ""))
        scored: list[SearchHit] = []
        with self._lock:
            rows = list(self._rows.values())

        for record in rows:
            if record.kb_id not in allowed or not record.enabled:
                continue
            cosine = _cosine(query_vector, record.dense)
            if mode == "hybrid":
                doc_tokens = set(_tokenize(record.content or ""))
                lexical = len(query_tokens & doc_tokens) / len(query_tokens) if query_tokens else 0.0
                score = alpha * cosine + (1 - alpha) * lexical
            else:
                score = cosine
            scored.append(
                SearchHit(
                    chunk_id=record.chunk_id,
                    doc_id=record.doc_id,
                    kb_id=record.kb_id,
                    content=record.content,
                    score=score,
                    page_no=record.page_no,
                )
            )

        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[: max(1, int(top_k))]

    def health(self) -> str:
        return "ok"

    def count(self, kb_id: int | None = None) -> int:
        with self._lock:
            if kb_id is None:
                return len(self._rows)
            return sum(1 for row in self._rows.values() if row.kb_id == int(kb_id))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """余弦相似度。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / ((left_norm**0.5) * (right_norm**0.5))


_STORE_CACHE: dict[str, object] = {}


def build_vector_store(cfg: Settings | None = None):
    """按配置创建向量库。"""
    cfg = cfg or current_settings()
    provider = (cfg.milvus.provider or "milvus").lower()
    if provider in ("memory", "in-memory", "local"):
        logger.info("使用内存向量库（无需 Milvus）")
        return MemoryVectorStore(cfg)
    return MilvusVectorStore(cfg)


def get_vector_store(cfg: Settings | None = None):
    """获取向量库单例。"""
    cfg = cfg or current_settings()
    key = f"{cfg.milvus.provider}:{cfg.milvus.uri}:{cfg.milvus.collection}:{cfg.embedding.dimension}"
    if key not in _STORE_CACHE:
        _STORE_CACHE[key] = build_vector_store(cfg)
    return _STORE_CACHE[key]


def reset_vector_store() -> None:
    """清空缓存（测试用）。"""
    _STORE_CACHE.clear()


__all__ = [
    "VectorRecord",
    "SearchHit",
    "VectorStoreError",
    "MilvusVectorStore",
    "MemoryVectorStore",
    "build_vector_store",
    "get_vector_store",
    "reset_vector_store",
]
