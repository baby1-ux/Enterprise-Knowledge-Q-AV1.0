"""Markdown / 纯文本解析：按标题与空行划分逻辑块。"""

from __future__ import annotations

import re
from pathlib import Path

from ...core.logging import get_logger
from .base import BaseParser, ParseError, ParsedBlock

logger = get_logger("parser.markdown")

_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1")
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")


def read_text_file(path: Path) -> str:
    """按常见编码依次尝试读取文本文件。"""
    raw = path.read_bytes()
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


class MarkdownParser(BaseParser):
    """Markdown 解析器：以标题为界切分逻辑块，保留标题层级信息。"""

    extensions = (".md", ".markdown")

    def parse(self, path: Path) -> list[ParsedBlock]:
        self._ensure_exists(path)
        text = read_text_file(path)
        if not text.strip():
            raise ParseError("Markdown 文件内容为空")

        blocks: list[ParsedBlock] = []
        current_lines: list[str] = []
        current_title = ""
        heading_stack: list[tuple[int, str]] = []

        def flush() -> None:
            content = self._clean_text("\n".join(current_lines))
            if content:
                blocks.append(
                    ParsedBlock(text=content, page_no=None, meta={"source": path.name, "title": current_title})
                )

        for line in text.splitlines():
            match = _HEADING_PATTERN.match(line.strip())
            if match:
                flush()
                current_lines = [line.strip()]
                level = len(match.group(1))
                title = match.group(2).strip()
                heading_stack = [(lv, tx) for lv, tx in heading_stack if lv < level]
                heading_stack.append((level, title))
                current_title = " / ".join(tx for _, tx in heading_stack)
            else:
                current_lines.append(line)
        flush()

        if not blocks:
            raise ParseError("未从 Markdown 中提取到有效内容")
        logger.info("Markdown 解析完成：%s，共 %s 个逻辑块", path.name, len(blocks))
        return blocks


class TextParser(BaseParser):
    """纯文本解析器：按空行划分段落块。"""

    extensions = (".txt",)

    def parse(self, path: Path) -> list[ParsedBlock]:
        self._ensure_exists(path)
        text = read_text_file(path)
        if not text.strip():
            raise ParseError("文本文件内容为空")

        blocks: list[ParsedBlock] = []
        for paragraph in re.split(r"\n\s*\n", text):
            cleaned = self._clean_text(paragraph)
            if cleaned:
                blocks.append(ParsedBlock(text=cleaned, page_no=None, meta={"source": path.name}))
        if not blocks:
            raise ParseError("未从文本中提取到有效内容")
        logger.info("文本解析完成：%s，共 %s 个段落块", path.name, len(blocks))
        return blocks
