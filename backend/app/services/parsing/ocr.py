"""图片文字识别（OCR）：默认使用通义千问 qwen-vl-ocr，本地可用 pytesseract。"""

from __future__ import annotations

import base64
from pathlib import Path

import requests

from ...core.config import Settings, is_placeholder_api_key, settings as current_settings
from ...core.logging import get_logger
from .base import ParseError

logger = get_logger("parser.ocr")

_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


class OcrClient:
    """OCR 客户端，按配置选择云端或本地引擎。"""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or current_settings()
        self.provider = self.settings.parser.ocr.provider

    def recognize(self, image_path: Path) -> str:
        """识别图片中的文字。"""
        provider = (self.provider or "dashscope").lower()
        if provider == "pytesseract":
            return self._recognize_local(image_path)
        return self._recognize_dashscope(image_path)

    # ------------------------------------------------------------------
    def _recognize_dashscope(self, image_path: Path) -> str:
        """调用 DashScope 多模态 OCR（qwen-vl-ocr）。

        对话模型已切换为 DeepSeek，而 DeepSeek 暂不提供图片理解接口，
        因此 OCR 仍使用 DashScope，Key 独立配置在 parser.ocr.api_key。
        """
        api_key = self.settings.parser.ocr.api_key
        if is_placeholder_api_key(api_key):
            raise ParseError(
                "图片解析需要 DashScope API Key（config.yaml -> parser.ocr.api_key，或环境变量 DASHSCOPE_API_KEY）"
            )

        suffix = image_path.suffix.lower()
        mime = _MIME_MAP.get(suffix, "image/png")
        try:
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ParseError(f"读取图片失败：{exc}") from exc

        url = f"{self.settings.parser.ocr.base_url.rstrip('/')}/services/aigc/multimodal-generation/generation"
        payload = {
            "model": self.settings.parser.ocr.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": f"data:{mime};base64,{encoded}"},
                            {"text": "请识别并输出图片中的全部文字，保持原有段落顺序，不要添加解释。"},
                        ],
                    }
                ]
            },
            "parameters": {"temperature": 0.0},
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=self.settings.parser.ocr.timeout
            )
        except requests.RequestException as exc:
            raise ParseError(f"OCR 服务请求失败：{exc}") from exc

        if response.status_code != 200:
            logger.error("OCR 调用失败 status=%s body=%s", response.status_code, response.text[:500])
            raise ParseError(f"OCR 服务返回错误（HTTP {response.status_code}）：{response.text[:200]}")

        data = response.json()
        choices = (data.get("output") or {}).get("choices") or []
        texts: list[str] = []
        for choice in choices:
            content = ((choice.get("message") or {}).get("content")) or []
            if isinstance(content, str):
                texts.append(content)
                continue
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    texts.append(str(item["text"]))
        text = "\n".join(part.strip() for part in texts if part and part.strip())
        if not text:
            logger.warning("OCR 未识别到文字：%s", image_path.name)
        return text

    # ------------------------------------------------------------------
    def _recognize_local(self, image_path: Path) -> str:
        """本地 pytesseract 识别（需额外安装 tesseract 与语言包）。"""
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise ParseError("本地 OCR 未安装，请执行 pip install pytesseract 或改用 dashscope 方式") from exc

        try:
            image = Image.open(image_path)
            return pytesseract.image_to_string(image, lang=self.settings.parser.ocr.language).strip()
        except Exception as exc:  # pragma: no cover - 依赖外部程序
            raise ParseError(f"本地 OCR 识别失败：{exc}") from exc
