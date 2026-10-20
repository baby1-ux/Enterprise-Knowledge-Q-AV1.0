"""文本切块：按段落/句子边界切分，支持重叠，避免切断语义。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.logging import get_logger
from .parsing.base import ParsedBlock

logger = get_logger("splitter")

# 中文句子结束符（保留在片段末尾）
_SENTENCE_END = "。！？；!?;\n"
_PUNCTUATION = "。！？；，、,;.!?:："


@dataclass
class TextChunk:
    """切块结果。"""

    content: str
    chunk_index: int = 0
    page_no: int | None = None


class TextSplitter:
    """字符级切块器（中文友好）。"""

    MIN_CHUNK_SIZE = 20

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        if chunk_size < self.MIN_CHUNK_SIZE:
            raise ValueError(f"切块大小不能小于 {self.MIN_CHUNK_SIZE}")
        if chunk_overlap < 0:
            raise ValueError("重叠大小不能为负数")
        if chunk_overlap >= chunk_size:
            raise ValueError("重叠大小必须小于切块大小")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    def split_text(self, text: str) -> list[str]:
        """把长文本切分为若干块。"""
        segments = self._segment(text)
        if not segments:
            return []
        return self._pack(segments)

    def split_blocks(self, blocks: list[ParsedBlock]) -> list[TextChunk]:
        """把多个解析块切块，并保留每块的页码信息。"""
        chunks: list[TextChunk] = []
        index = 0
        for block in blocks:
            for content in self.split_text(block.text):
                chunks.append(TextChunk(content=content, chunk_index=index, page_no=block.page_no))
                index += 1
        logger.debug("切块完成：块数=%s，切块大小=%s，重叠=%s", len(chunks), self.chunk_size, self.chunk_overlap)
        return chunks

    # ------------------------------------------------------------------
    def _segment(self, text: str) -> list[str]:
        """把文本拆成句子级片段（不超过 chunk_size）。"""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        segments: list[str] = []

        for paragraph in re.split(r"\n\s*\n", normalized):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            for line in paragraph.split("\n"):
                line = line.strip()
                if not line:
                    continue
                pieces = self._split_line(line)
                if pieces:
                    # 行末保留换行符，避免相邻行被拼成一句；同时确保片段不超长
                    if len(pieces[-1]) < self.chunk_size:
                        pieces[-1] = pieces[-1] + "\n"
                    segments.extend(pieces)

        return segments

    def _split_line(self, line: str) -> list[str]:
        """按句子结束符切分单行文本，超长句子硬切。"""
        pieces: list[str] = []
        buffer = ""
        for char in line:
            buffer += char
            if char in _SENTENCE_END:
                pieces.append(buffer)
                buffer = ""
            elif len(buffer) >= self.chunk_size:
                # 超长句子：优先在标点处断开
                cut = max(buffer.rfind(p) for p in _PUNCTUATION) if any(p in buffer for p in _PUNCTUATION) else -1
                if cut >= self.MIN_CHUNK_SIZE:
                    pieces.append(buffer[: cut + 1])
                    buffer = buffer[cut + 1 :]
                else:
                    pieces.append(buffer)
                    buffer = ""
        if buffer.strip():
            pieces.append(buffer)
        return [piece.strip() for piece in pieces if piece.strip()]

    def _pack(self, segments: list[str]) -> list[str]:
        """贪心合并片段为块，块之间保留重叠片段。"""
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for segment in segments:
            segment_len = len(segment)
            if current and current_len + segment_len > self.chunk_size:
                chunks.append(self._join(current))
                carry: list[str] = []
                carry_len = 0
                for item in reversed(current):
                    if carry_len + len(item) <= self.chunk_overlap:
                        carry.insert(0, item)
                        carry_len += len(item)
                    else:
                        break
                # 重叠后仍超出限制则放弃重叠，保证块不超长
                if carry_len + segment_len > self.chunk_size:
                    carry, carry_len = [], 0
                current, current_len = carry, carry_len

            if segment_len > self.chunk_size:
                # 理论上不会发生（_split_line 已限制长度），兜底硬切
                for start in range(0, segment_len, self.chunk_size):
                    piece = segment[start : start + self.chunk_size].strip()
                    if piece:
                        if current:
                            chunks.append(self._join(current))
                            current, current_len = [], 0
                        chunks.append(piece)
                continue

            current.append(segment)
            current_len += segment_len

        if current:
            chunks.append(self._join(current))
        return [chunk for chunk in chunks if chunk.strip()]

    @staticmethod
    def _join(parts: list[str]) -> str:
        """拼接片段并清理多余空行。"""
        text = "".join(parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def split_into_chunks(
    blocks: list[ParsedBlock], chunk_size: int = 500, chunk_overlap: int = 50
) -> list[TextChunk]:
    """便捷函数：解析块 -> 切块。"""
    return TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap).split_blocks(blocks)
