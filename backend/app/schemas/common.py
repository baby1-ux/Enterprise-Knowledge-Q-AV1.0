"""通用响应模型与时间格式化工具。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_datetime(value: datetime | None) -> str | None:
    """统一时间格式：2026-07-10 10:00:00。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime(DATETIME_FORMAT)


class ApiResponse(BaseModel):
    """统一响应结构。"""

    code: int = 0
    message: str = "ok"
    data: Any = None


class PageData(BaseModel, Generic[T]):
    """分页数据。"""

    total: int = 0
    page: int = 1
    page_size: int = 10
    items: list[T] = []


class ORMSchema(BaseModel):
    """从 ORM 对象转换的基类。"""

    model_config = ConfigDict(from_attributes=True)


class TimestampSchema(ORMSchema):
    """带创建/更新时间的响应基类。

    时间统一由业务层的 to_dict 函数格式化为 `YYYY-MM-DD HH:MM:SS` 字符串后传入，
    避免依赖序列化器，保证 MySQL / SQLite 下表现一致。
    """

    created_at: str | None = None
    updated_at: str | None = None
