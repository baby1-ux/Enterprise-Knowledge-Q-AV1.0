"""对话相关的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .common import TimestampSchema
from .kb import _validate_mode

FEEDBACK_CHOICES = ("like", "dislike")


class ModelOptionOut(BaseModel):
    """可选大模型。"""

    value: str
    label: str
    description: str = ""


class ChatDefaultsOut(BaseModel):
    """默认推理参数。"""

    model: str = "deepseek-chat"
    temperature: float = 0.3
    top_p: float = 0.8
    max_tokens: int = 2048
    history_rounds: int = 5
    retrieval_mode: str = "hybrid"


class ChatModelsOut(BaseModel):
    """模型与默认参数。"""

    models: list[ModelOptionOut] = []
    defaults: ChatDefaultsOut = Field(default_factory=ChatDefaultsOut)


class SessionParamsMixin(BaseModel):
    """会话可配置参数（带取值范围校验）。"""

    model: str | None = Field(None, max_length=64, description="大模型名称")
    temperature: float | None = Field(None, ge=0.0, le=2.0, description="温度，0~2")
    top_p: float | None = Field(None, gt=0.0, le=1.0, description="topP，0~1")
    max_tokens: int | None = Field(None, ge=64, le=8192, description="最长输出 token 数")
    history_rounds: int | None = Field(None, ge=0, le=20, description="历史对话轮数")
    retrieval_mode: str | None = Field(None, description="dense（稠密）/ hybrid（混合）")

    @field_validator("retrieval_mode")
    @classmethod
    def check_mode(cls, value: str | None) -> str | None:
        return None if value is None else _validate_mode(value)


class SessionCreate(SessionParamsMixin):
    """新建会话。"""

    name: str | None = Field(None, max_length=128, description="会话名称")
    kb_ids: list[int] = Field(default_factory=list, description="选中的知识库 ID")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SessionUpdate(SessionParamsMixin):
    """更新会话（字段均可选）。"""

    name: str | None = Field(None, max_length=128)
    kb_ids: list[int] | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SessionOut(TimestampSchema):
    """会话信息。"""

    id: int
    name: str
    kb_ids: list[int] = []
    kb_names: list[str] = []
    model: str = "deepseek-chat"
    temperature: float = 0.3
    top_p: float = 0.8
    max_tokens: int = 2048
    history_rounds: int = 5
    retrieval_mode: str = "hybrid"
    created_at: str | None = None
    updated_at: str | None = None


class CitationOut(BaseModel):
    """回答引用来源。"""

    index: int = 0
    chunk_id: int = 0
    doc_id: int = 0
    doc_name: str = ""
    kb_id: int = 0
    kb_name: str = ""
    page_no: int | None = None
    score: float = 0.0
    preview: str = ""


class MessageOut(TimestampSchema):
    """对话消息。"""

    id: int
    role: str
    content: str
    citations: list[CitationOut] = []
    feedback: str | None = None
    created_at: str | None = None


class MessageFeedbackUpdate(BaseModel):
    """消息反馈：like（点赞）/ dislike（点踩）/ null（取消）。"""

    feedback: str | None = Field(None, description="like / dislike，传 null 取消反馈")

    @field_validator("feedback")
    @classmethod
    def check_feedback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in FEEDBACK_CHOICES:
            raise ValueError("反馈仅支持 like（点赞）或 dislike（点踩）")
        return value


class ChatStreamRequest(SessionParamsMixin):
    """流式问答请求。"""

    session_id: int = Field(..., ge=1, description="会话 ID")
    question: str = Field(..., min_length=1, max_length=4000, description="用户问题")
    kb_ids: list[int] | None = Field(None, description="本次使用的知识库（覆盖会话配置）")

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value
