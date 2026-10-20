"""知识库、文档、分块相关的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .common import TimestampSchema

RETRIEVAL_MODES = ("dense", "hybrid")


def _validate_mode(value: str) -> str:
    value = (value or "").strip().lower()
    if value not in RETRIEVAL_MODES:
        raise ValueError("检索方式仅支持 dense（稠密检索）或 hybrid（混合检索）")
    return value


class KnowledgeBaseCreate(BaseModel):
    """创建知识库。"""

    name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    description: str = Field("", max_length=512, description="知识库描述")
    retrieval_mode: str = Field("hybrid", description="默认检索方式")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("知识库名称不能为空")
        return value

    @field_validator("retrieval_mode")
    @classmethod
    def check_mode(cls, value: str) -> str:
        return _validate_mode(value)


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库（字段均可选）。"""

    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)
    retrieval_mode: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("知识库名称不能为空")
        return value

    @field_validator("retrieval_mode")
    @classmethod
    def check_mode(cls, value: str | None) -> str | None:
        return None if value is None else _validate_mode(value)


class KnowledgeBaseOut(TimestampSchema):
    """知识库信息。"""

    id: int
    name: str
    description: str = ""
    retrieval_mode: str = "hybrid"
    doc_count: int = 0
    chunk_count: int = 0
    created_at: str | None = None


class DocumentOut(TimestampSchema):
    """文档信息。"""

    id: int
    kb_id: int
    filename: str
    file_type: str = ""
    size: int = 0
    status: str = "pending"
    error_message: str = ""
    chunk_count: int = 0
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_mode: str = "hybrid"
    created_at: str | None = None


class DocumentStatusOut(BaseModel):
    """文档解析进度。"""

    id: int
    status: str
    chunk_count: int = 0
    error_message: str = ""


class ChunkOut(TimestampSchema):
    """分块信息。"""

    id: int
    document_id: int = 0
    chunk_index: int = 0
    content: str
    page_no: int | None = None
    enabled: bool = True
    created_at: str | None = None


class ChunkPageOut(BaseModel):
    """分块分页结果。"""

    total: int = 0
    page: int = 1
    page_size: int = 10
    items: list[ChunkOut] = []


class ChunkUpdate(BaseModel):
    """更新分块内容。"""

    content: str = Field(..., min_length=1, max_length=8000, description="分块文本")

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分块内容不能为空")
        return value


class ChunkEnabledUpdate(BaseModel):
    """启停分块。"""

    enabled: bool
