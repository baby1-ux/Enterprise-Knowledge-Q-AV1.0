"""大模型客户端：DeepSeek（OpenAI 兼容接口），支持流式输出与推理模型。

支持的模型（见 config.yaml -> llm.models）：
  - deepseek-chat     ：通用对话模型（DeepSeek-V3），支持 temperature / topP
  - deepseek-reasoner ：推理模型（DeepSeek-R1），会先输出思考过程，再给出答案；
                        该模型不接受 temperature / topP 等采样参数，客户端会自动省略，
                        并且只向前端输出最终答案（思考内容不作为答案返回）。
"""

from __future__ import annotations

from typing import Iterator, Sequence

from ..core.config import Settings, is_placeholder_api_key, settings as current_settings
from ..core.logging import get_logger

logger = get_logger("llm")

Message = dict[str, str]


class LLMError(Exception):
    """大模型调用失败。"""


class LLMClient:
    """DeepSeek 对话客户端。"""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.settings = cfg or current_settings()
        self.provider = self.settings.llm.provider
        self.api_key = self.settings.llm.api_key
        self.base_url = self.settings.llm.base_url
        self.default_model = self.settings.llm.default_model
        self.timeout = self.settings.llm.timeout
        self._client = None

    # ------------------------------------------------------------------ 基础信息
    @property
    def configured(self) -> bool:
        """是否已配置可用的 API Key。"""
        return not is_placeholder_api_key(self.api_key)

    @property
    def model_options(self) -> list[dict[str, str]]:
        """可选模型列表。"""
        return [
            {"value": option.value, "label": option.label, "description": option.description}
            for option in self.settings.llm.models
        ]

    @staticmethod
    def is_reasoner(model: str | None) -> bool:
        """是否为推理模型（R1 系列，不支持采样参数）。"""
        name = (model or "").lower()
        return "reasoner" in name or "-r1" in name or name.endswith("r1")

    def _get_client(self):
        """惰性创建 OpenAI 兼容客户端。"""
        if not self.configured:
            raise LLMError("未配置 DeepSeek API Key，请在 config.yaml 的 llm.api_key 或环境变量 DEEPSEEK_API_KEY 中填写")
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise LLMError("缺少 openai 依赖，无法调用大模型") from exc
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, max_retries=1)
        return self._client

    # ------------------------------------------------------------------ 请求体
    def build_payload(
        self,
        messages: Sequence[Message],
        model: str | None = None,
        temperature: float = 0.3,
        top_p: float = 0.8,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> dict:
        """构造请求体：推理模型自动省略 temperature / top_p。"""
        model_name = model or self.default_model
        payload: dict = {
            "model": model_name,
            "messages": list(messages),
            "max_tokens": int(max_tokens),
            "stream": bool(stream),
        }
        if self.is_reasoner(model_name):
            logger.info("推理模型不支持采样参数，本次忽略温度与 topP：model=%s", model_name)
        else:
            payload["temperature"] = float(temperature)
            payload["top_p"] = float(top_p)
        return payload

    # ------------------------------------------------------------------ 调用
    def stream_chat(
        self,
        messages: Sequence[Message],
        model: str | None = None,
        temperature: float = 0.3,
        top_p: float = 0.8,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """流式对话，逐段产出最终答案文本（推理模型的思考过程会被跳过）。"""
        client = self._get_client()
        payload = self.build_payload(messages, model, temperature, top_p, max_tokens, stream=True)
        logger.info(
            "开始调用大模型：model=%s, stream=True, temperature=%s, top_p=%s, max_tokens=%s",
            payload["model"],
            payload.get("temperature", "不支持"),
            payload.get("top_p", "不支持"),
            payload["max_tokens"],
        )
        try:
            stream = client.chat.completions.create(**payload)
            for chunk in stream:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                # 只取最终答案；deepseek-reasoner 的 reasoning_content 不输出给用户
                content = getattr(delta, "content", None)
                if content:
                    yield content
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转换为业务异常
            logger.error("大模型流式调用失败：%s", exc)
            raise LLMError(f"大模型调用失败：{exc}") from exc

    def complete(
        self,
        messages: Sequence[Message],
        model: str | None = None,
        temperature: float = 0.3,
        top_p: float = 0.8,
        max_tokens: int = 1024,
    ) -> str:
        """非流式调用，返回完整文本（用于问题改写等辅助场景）。"""
        client = self._get_client()
        payload = self.build_payload(messages, model, temperature, top_p, max_tokens, stream=False)
        try:
            response = client.chat.completions.create(**payload)
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("大模型调用失败：%s", exc)
            raise LLMError(f"大模型调用失败：{exc}") from exc


_LLM_CACHE: dict[str, LLMClient] = {}


def get_llm(cfg: Settings | None = None) -> LLMClient:
    """获取大模型客户端。"""
    cfg = cfg or current_settings()
    key = f"{cfg.llm.provider}:{cfg.llm.base_url}:{cfg.llm.default_model}:{bool(cfg.llm.api_key)}"
    if key not in _LLM_CACHE:
        _LLM_CACHE[key] = LLMClient(cfg)
    return _LLM_CACHE[key]


def reset_llm() -> None:
    """清空缓存（测试用）。"""
    _LLM_CACHE.clear()
