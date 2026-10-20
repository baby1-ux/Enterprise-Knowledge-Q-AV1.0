"""PDF 解析：按页提取文本。"""

from __future__ import annotations

from pathlib import Path

from ...core.config import Settings, settings as current_settings
from ...core.logging import get_logger
from .base import BaseParser, ParseError, ParsedBlock

logger = get_logger("parser.pdf")


class PDFParser(BaseParser):
    """基于 pypdf 的 PDF 解析器。"""

    extensions = (".pdf",)

    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or current_settings()

    def parse(self, path: Path) -> list[ParsedBlock]:
        self._ensure_exists(path)
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise ParseError("缺少 pypdf 依赖，无法解析 PDF") from exc

        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise ParseError(f"PDF 文件无法打开，可能已损坏：{exc}") from exc

        max_pages = self.settings.parser.pdf.max_pages
        blocks: list[ParsedBlock] = []
        total_pages = len(reader.pages)
        for index, page in enumerate(reader.pages[:max_pages]):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover - 个别页面损坏
                logger.warning("第 %s 页解析失败：%s", index + 1, exc)
                continue
            cleaned = self._clean_text(text)
            if cleaned:
                blocks.append(ParsedBlock(text=cleaned, page_no=index + 1, meta={"source": path.name}))

        if total_pages > max_pages:
            logger.info("PDF 共 %s 页，仅解析前 %s 页", total_pages, max_pages)
        if not blocks:
            raise ParseError("未从 PDF 中提取到文本（可能是扫描件，请转换为图片后按图片解析）")
        logger.info("PDF 解析完成：%s，共 %s 页文本", path.name, len(blocks))
        return blocks
