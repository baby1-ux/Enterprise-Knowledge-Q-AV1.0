"""文本切块单元测试。"""

from __future__ import annotations

import pytest

from app.services.parsing.base import ParsedBlock
from app.services.splitter import TextSplitter, split_into_chunks


def _long_text(count: int = 200) -> str:
    return "。".join(f"第{i}条：员工需要遵守公司规定并按时提交周报" for i in range(count)) + "。"


def test_chunk_length_never_exceeds_limit() -> None:
    """每个分块长度都不超过设定的切块大小。"""
    splitter = TextSplitter(chunk_size=200, chunk_overlap=20)
    chunks = splitter.split_text(_long_text())
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_chunks_keep_content_continuity() -> None:
    """切块结果覆盖原文首尾内容，没有明显丢失。"""
    text = _long_text(20)
    chunks = TextSplitter(chunk_size=150, chunk_overlap=30).split_text(text)
    joined = "".join(chunks)
    assert "第0条" in joined
    assert "第19条" in joined


def test_overlap_produces_shared_content() -> None:
    """相邻分块之间存在重叠内容。"""
    text = _long_text(30)
    chunks = TextSplitter(chunk_size=200, chunk_overlap=50).split_text(text)
    assert len(chunks) >= 2
    overlapped = any(
        chunks[index][-20:].strip() and chunks[index][-20:].strip() in chunks[index + 1]
        for index in range(len(chunks) - 1)
    )
    assert overlapped


def test_short_text_single_chunk() -> None:
    """短文本不切分。"""
    chunks = TextSplitter(chunk_size=200, chunk_overlap=10).split_text("保修期为一年。")
    assert chunks == ["保修期为一年。"]


def test_empty_text_returns_no_chunk() -> None:
    """空文本不产生分块。"""
    assert TextSplitter().split_text("   \n\n  ") == []


@pytest.mark.parametrize(
    "chunk_size,chunk_overlap",
    [(10, 0), (100, 100), (100, 150), (100, -1)],
)
def test_invalid_parameters_rejected(chunk_size: int, chunk_overlap: int) -> None:
    """非法切块参数直接报错。"""
    with pytest.raises(ValueError):
        TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def test_split_blocks_keeps_page_number() -> None:
    """split_blocks 保留来源页码与序号。"""
    blocks = [
        ParsedBlock(text="第一页内容。保修期为一年。", page_no=1),
        ParsedBlock(text="第二页内容。退货需在 7 天内申请。", page_no=2),
    ]
    chunks = split_into_chunks(blocks, chunk_size=50, chunk_overlap=10)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].page_no == 1
    assert chunks[-1].page_no == 2


def test_split_blocks_without_page_number() -> None:
    """无页码信息时保持 None。"""
    chunks = split_into_chunks([ParsedBlock(text="纯文本内容，没有页码。")], chunk_size=50, chunk_overlap=5)
    assert all(chunk.page_no is None for chunk in chunks)
