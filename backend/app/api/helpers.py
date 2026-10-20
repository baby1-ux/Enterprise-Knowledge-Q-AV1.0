"""通用响应助手与 SSE 编码。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应。"""
    return {"code": 0, "message": message, "data": data}


def dump(model: BaseModel) -> dict[str, Any]:
    """把 Pydantic 模型转为可 JSON 化的字典（应用自定义时间格式）。"""
    return model.model_dump(mode="json")


def dump_list(models: list[BaseModel]) -> list[dict[str, Any]]:
    """批量转换。"""
    return [model.model_dump(mode="json") for model in models]


def sse_event(event: str, data: dict[str, Any]) -> str:
    """编码单个 SSE 事件。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
