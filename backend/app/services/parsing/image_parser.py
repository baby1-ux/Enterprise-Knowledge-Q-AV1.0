"""图片解析：通过 OCR 提取文字。"""

from __future__ import annotations

from pathlib import Path

from ...core.config import Settings, settings as current_settings
from ...core.logging import get_logger
from .base import BaseParser, ParseError, ParsedBlock
from .ocr import OcrClient

logger = get_logger("parser.image")


class ImageParser(BaseParser):
    """图片 OCR 解析器。"""

    extensions = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or current_settings()
        self.ocr = OcrClient(self.settings)

    def parse(self, path: Path) -> list[ParsedBlock]:
        self._ensure_exists(path)
        text = self.ocr.recognize(path)
        cleaned = self._clean_text(text)
        if not cleaned:
            raise ParseError("未从图片中识别到文字，请更换更清晰的图片")
        logger.info("图片解析完成：%s，识别字符数 %s", path.name, len(cleaned))
        return [ParsedBlock(text=cleaned, page_no=1, meta={"source": path.name})]
