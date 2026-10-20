"""解析器基类与数据结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ParseError(Exception):
    """文档解析失败，message 为中文提示。"""


@dataclass
class ParsedBlock:
    """解析出的文本块（尚未切块），携带来源页码等信息。"""

    text: str
    page_no: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()


class BaseParser(ABC):
    """所有解析器的基类。"""

    #: 支持的文件后缀（小写，含点）
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, path: Path) -> list[ParsedBlock]:
        """解析文件，返回文本块列表。"""

    def _ensure_exists(self, path: Path) -> None:
        if not path.exists():
            raise ParseError(f"文件不存在：{path.name}")
        if path.stat().st_size == 0:
            raise ParseError(f"文件内容为空：{path.name}")

    @staticmethod
    def _clean_text(text: str) -> str:
        """规整空白字符，去掉零宽字符。"""
        if not text:
            return ""
        text = text.replace("\u200b", "").replace("\xa0", " ")
        lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        cleaned: list[str] = []
        blank = 0
        for line in lines:
            if line:
                blank = 0
                cleaned.append(line)
            else:
                blank += 1
                if blank <= 1:
                    cleaned.append("")
        return "\n".join(cleaned).strip()
