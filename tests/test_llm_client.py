"""大模型客户端单元测试：DeepSeek 请求体构造、推理模型采样参数处理、Key 校验。

不发起任何网络请求，只校验请求体与状态判断逻辑。
"""

from __future__ import annotations

import pytest

from app.services.llm import LLMClient, LLMError

MESSAGES = [
    {"role": "system", "content": "你是企业知识库助手。"},
    {"role": "user", "content": "产品保修期是多久？"},
]


def test_build_payload_for_chat_model(test_settings) -> None:
    """deepseek-chat 携带温度与 topP 参数。"""
    client = LLMClient(test_settings)
    payload = client.build_payload(MESSAGES, model="deepseek-chat", temperature=0.7, top_p=0.5, max_tokens=512)

    assert payload["model"] == "deepseek-chat"
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.5
    assert payload["max_tokens"] == 512
    assert payload["stream"] is False
    assert payload["messages"] == MESSAGES


def test_build_payload_for_reasoner_omits_sampling(test_settings) -> None:
    """deepseek-reasoner 不传 temperature / top_p（否则接口报 400）。"""
    client = LLMClient(test_settings)
    payload = client.build_payload(MESSAGES, model="deepseek-reasoner", temperature=0.7, top_p=0.5, max_tokens=1024)

    assert payload["model"] == "deepseek-reasoner"
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert payload["max_tokens"] == 1024
    assert payload["stream"] is False


def test_build_payload_stream_flag(test_settings) -> None:
    """流式调用时 stream=True。"""
    client = LLMClient(test_settings)
    payload = client.build_payload(MESSAGES, stream=True)
    assert payload["stream"] is True
    assert payload["model"] == "deepseek-chat"  # 未指定模型时使用默认模型


@pytest.mark.parametrize(
    "model,expected",
    [
        ("deepseek-chat", False),
        ("deepseek-reasoner", True),
        ("deepseek-r1", True),
        ("DeepSeek-Reasoner", True),
        ("", False),
        (None, False),
    ],
)
def test_is_reasoner_detection(model, expected: bool) -> None:
    """推理模型识别。"""
    assert LLMClient.is_reasoner(model) is expected


def test_configured_with_real_key(test_settings) -> None:
    """真实 Key 视为已配置。"""
    test_settings.llm.api_key = "sk-deepseek-abcdef"
    assert LLMClient(test_settings).configured is True


@pytest.mark.parametrize("key", ["", "sk-请替换为你的DeepSeek-API-Key", "your-api-key"])
def test_configured_with_placeholder_key(test_settings, key: str) -> None:
    """占位 Key 视为未配置。"""
    test_settings.llm.api_key = key
    assert LLMClient(test_settings).configured is False


def test_stream_chat_raises_without_key(test_settings) -> None:
    """未配置 Key 时调用流式问答抛出中文异常。"""
    test_settings.llm.api_key = ""
    client = LLMClient(test_settings)
    with pytest.raises(LLMError) as excinfo:
        list(client.stream_chat(MESSAGES))
    assert "DeepSeek API Key" in str(excinfo.value)


def test_model_options_exposed(test_settings) -> None:
    """模型下拉数据来自配置，并包含推理模型。"""
    options = LLMClient(test_settings).model_options
    values = [option["value"] for option in options]
    assert values == ["deepseek-chat", "deepseek-reasoner"]
    assert all(option["label"] for option in options)
