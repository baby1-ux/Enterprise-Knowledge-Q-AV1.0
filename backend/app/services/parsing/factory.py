"""解析器工厂：根据文件后缀选择解析器。"""

from __future__ import annotations

from pathlib import Path

from ...core.config import Settings, settings as current_settings
from ...core.logging import get_logger
from .base import BaseParser, ParseError, ParsedBlock
from .docx_parser import DocxParser
from .image_parser import ImageParser
from .markdown_parser import MarkdownParser, TextParser
from .pdf_parser import PDFParser
from .pptx_parser import PptParser, PptxParser

logger = get_logger("parser.factory")


def _build_registry(cfg: Settings | None = None) -> dict[str, BaseParser]:
    """构建 后缀 -> 解析器 的映射。"""
    parsers: list[BaseParser] = [
        PDFParser(cfg),
        PptParser(),
        PptxParser(),
        MarkdownParser(),
        TextParser(),
        DocxParser(),
        ImageParser(cfg),
    ]
    registry: dict[str, BaseParser] = {}
    for parser in parsers:
        for extension in parser.extensions:
            registry[extension] = parser
    return registry


def supported_extensions() -> list[str]:
    """返回全部支持的文件后缀。"""
    return sorted(_build_registry().keys())


def get_parser(filename_or_suffix: str, cfg: Settings | None = None) -> BaseParser:
    """根据文件名或后缀获取解析器。"""
    text = str(filename_or_suffix).lower()
    suffix = text if text.startswith(".") else Path(text).suffix.lower()
    registry = _build_registry(cfg)
    parser = registry.get(suffix)
    if parser is None:
        raise ParseError(f"暂不支持该文件类型（{suffix or '未知'}），支持：{'、'.join(supported_extensions())}")
    return parser


def parse_document(path: Path, cfg: Settings | None = None) -> list[ParsedBlock]:
    """解析文档并返回文本块列表（自动筛选非空块）。"""
    parser = get_parser(path.name, cfg)
    blocks = parser.parse(path)
    result = [block for block in blocks if not block.is_empty()]
    if not result:
        raise ParseError("文档中未解析到有效文本内容")
    logger.info("文档解析完成：%s，块数=%s", path.name, len(result))
    return result


__all__ = [
    "BaseParser",
    "ParsedBlock",
    "ParseError",
    "get_parser",
    "parse_document",
    "supported_extensions",
]
