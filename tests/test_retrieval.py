"""检索链路单元测试：哈希向量化 + 内存向量库 + 检索器。"""

from __future__ import annotations

import pytest

from app.services.embedding import HashEmbedder, _tokenize
from app.services.retriever import RetrievalError, Retriever
from app.services.vector_store import MemoryVectorStore, VectorRecord

CORPUS = [
    (1, "产品保修期为一年，自购买之日起计算。"),
    (2, "退货需要在签收后 7 天内提交申请。"),
    (3, "公司总部位于杭州市西湖区。"),
]


@pytest.fixture()
def retriever_bundle(app_env):
    """构造检索器 + 内存向量库，并写入测试语料。"""
    cfg = app_env
    embedder = HashEmbedder(cfg.embedding.dimension)
    store = MemoryVectorStore(cfg)
    vectors = embedder.embed_documents([text for _, text in CORPUS])
    store.upsert(
        [
            VectorRecord(chunk_id=chunk_id, kb_id=1, doc_id=1, content=text, dense=vector, page_no=index + 1)
            for index, ((chunk_id, text), vector) in enumerate(zip(CORPUS, vectors))
        ]
    )
    retriever = Retriever(cfg, embedder=embedder, vector_store=store)
    return retriever, store, embedder


def test_retrieve_returns_most_relevant_chunk(retriever_bundle) -> None:
    """与问题最相关的分块排在第一位。"""
    retriever, _, _ = retriever_bundle
    hits = retriever.retrieve("产品保修期是多久", [1], top_k=2, mode="dense", score_threshold=0.0)
    assert hits
    assert "保修期" in hits[0].content
    assert hits[0].page_no == 1


def test_retrieve_without_kb_returns_empty(retriever_bundle) -> None:
    """未选择知识库时不返回任何结果。"""
    retriever, _, _ = retriever_bundle
    assert retriever.retrieve("保修期", [], top_k=3) == []


def test_retrieve_empty_query_returns_empty(retriever_bundle) -> None:
    """空问题不触发检索。"""
    retriever, _, _ = retriever_bundle
    assert retriever.retrieve("   ", [1]) == []


def test_retrieve_filters_other_knowledge_base(retriever_bundle) -> None:
    """只返回选中知识库的分块。"""
    retriever, _, _ = retriever_bundle
    assert retriever.retrieve("保修期", [99], top_k=3, score_threshold=0.0) == []


def test_retrieve_ignores_disabled_chunk(retriever_bundle) -> None:
    """禁用（enabled=False）的分块不参与检索。"""
    retriever, store, embedder = retriever_bundle
    vector = embedder.embed_query("公司总部位于杭州市西湖区。")
    store.upsert(
        [
            VectorRecord(
                chunk_id=3,
                kb_id=1,
                doc_id=1,
                content="公司总部位于杭州市西湖区。",
                dense=vector,
                page_no=3,
                enabled=False,
            )
        ]
    )
    hits = retriever.retrieve("公司总部位于哪里", [1], top_k=3, mode="dense", score_threshold=0.0)
    assert all(hit.chunk_id != 3 for hit in hits)


def test_retrieve_hybrid_mode(retriever_bundle) -> None:
    """混合检索（稠密 + 词法）同样返回相关分块。"""
    retriever, _, _ = retriever_bundle
    hits = retriever.retrieve("退货 7 天", [1], top_k=2, mode="hybrid", alpha=0.5)
    assert hits
    assert any("退货" in hit.content for hit in hits)


def test_retrieve_top_k_limit(retriever_bundle) -> None:
    """返回数量不超过 top_k。"""
    retriever, _, _ = retriever_bundle
    hits = retriever.retrieve("保修期 退货 地址", [1], top_k=2, mode="dense", score_threshold=0.0)
    assert len(hits) <= 2


def test_retrieve_raises_when_embedding_fails(app_env) -> None:
    """向量化失败时抛出中文异常。"""

    class BrokenEmbedder(HashEmbedder):
        def embed_query(self, text: str):  # noqa: ANN001
            from app.services.embedding import EmbeddingError

            raise EmbeddingError("模拟向量化失败")

    retriever = Retriever(app_env, embedder=BrokenEmbedder(64), vector_store=MemoryVectorStore(app_env))
    with pytest.raises(RetrievalError) as excinfo:
        retriever.retrieve("保修期", [1])
    assert "向量化失败" in str(excinfo.value)


def test_memory_store_delete_operations() -> None:
    """内存向量库支持按分块、文档、知识库删除。"""
    store = MemoryVectorStore()
    store.upsert(
        [
            VectorRecord(chunk_id=1, kb_id=1, doc_id=10, content="A", dense=[1.0, 0.0]),
            VectorRecord(chunk_id=2, kb_id=1, doc_id=10, content="B", dense=[0.0, 1.0]),
            VectorRecord(chunk_id=3, kb_id=2, doc_id=20, content="C", dense=[1.0, 1.0]),
        ]
    )
    assert store.count() == 3
    store.delete_chunks([1])
    assert store.count() == 2
    store.delete_by_documents([10])
    assert store.count() == 1
    store.delete_by_kb(2)
    assert store.count() == 0


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    """哈希向量稳定且已归一化，相同文本向量一致。"""
    embedder = HashEmbedder(64)
    first = embedder.embed_query("保修期为一年")
    second = embedder.embed_query("保修期为一年")
    assert first == second
    assert len(first) == 64
    norm = sum(value * value for value in first) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_tokenize_mixes_chinese_and_english() -> None:
    """分词同时覆盖中文 2-gram 与英文单词。"""
    tokens = _tokenize("RAG 检索增强")
    assert "rag" in tokens
    assert "检索" in tokens
