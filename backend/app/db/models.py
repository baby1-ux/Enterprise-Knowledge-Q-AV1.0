"""ORM 模型定义：用户、知识库、文档、分块、对话会话、对话消息。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """用户表。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")

    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User id={self.id} username={self.username!r}>"


class KnowledgeBase(Base, TimestampMixin):
    """知识库表：一个知识库可包含多个文档。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="知识库名称")
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="", comment="知识库描述")
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="向量模型")
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="向量维度")
    retrieval_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hybrid", comment="默认检索方式 dense/hybrid"
    )

    owner: Mapped[User] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<KnowledgeBase id={self.id} name={self.name!r}>"


class Document(Base, TimestampMixin):
    """文档表：记录上传文件与解析状态。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False, default="", comment="服务器保存路径")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="", comment="文件类型后缀")
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="文件大小（字节）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True, comment="pending/parsing/success/failed"
    )
    error_message: Mapped[str] = mapped_column(String(1024), nullable=False, default="", comment="失败原因")
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=500, comment="切块大小")
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=50, comment="重叠大小")
    retrieval_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hybrid", comment="解析时选择的检索方式"
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="分块数量")

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Document id={self.id} filename={self.filename!r} status={self.status!r}>"


class Chunk(Base, TimestampMixin):
    """分块表：文档解析后的文本块，与 Milvus 中的向量一一对应。"""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_document_chunk_index", "document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="块序号，从 0 开始")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分块文本")
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="来源页码/幻灯片序号")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否参与检索", server_default="1"
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Chunk id={self.id} index={self.chunk_index} doc={self.document_id}>"


class ChatSession(Base, TimestampMixin):
    """对话会话表：保存所选知识库与推理参数。"""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="新对话", comment="会话名称")
    kb_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list, comment="选中的知识库 ID 列表")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="deepseek-chat", comment="大模型")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.3, comment="温度")
    top_p: Mapped[float] = mapped_column(Float, nullable=False, default=0.8, comment="top_p")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048, comment="最长输出 token")
    history_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="历史对话轮数")
    retrieval_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hybrid", comment="检索方式 dense/hybrid"
    )

    user: Mapped[User] = relationship()
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def kb_ids_list(self) -> list[int]:
        """统一取出知识库 ID 列表（兼容 None 与字符串元素）。"""
        raw: Any = self.kb_ids or []
        result: list[int] = []
        for item in raw:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ChatSession id={self.id} name={self.name!r}>"


class ChatMessage(Base, TimestampMixin):
    """对话消息表：用户问题与助手回答。"""

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_id", "session_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user / assistant")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    citations: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True, comment="引用来源")
    feedback: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="用户反馈 like / dislike，仅助手消息"
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ChatMessage id={self.id} role={self.role!r}>"


__all__ = ["User", "KnowledgeBase", "Document", "Chunk", "ChatSession", "ChatMessage"]
