"""对话服务：会话管理 + RAG 流式问答（检索 → 组装提示词 → 流式生成 → 落库）。"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings, settings as current_settings
from ..core.errors import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..db.models import ChatMessage, ChatSession, Document, KnowledgeBase
from ..db.session import session_scope
from ..schemas.common import format_datetime
from .llm import LLMClient, LLMError, get_llm
from .prompt import (
    ContextItem,
    build_messages,
    build_rewrite_messages,
    session_title_from_question,
)
from .retriever import RetrievalError, Retriever, RetrievedChunk, get_retriever

logger = get_logger("chat_service")

DEFAULT_SESSION_NAME = "新对话"


class ChatService:
    """对话相关业务逻辑。"""

    def __init__(
        self,
        db: Session | None = None,
        cfg: Settings | None = None,
        retriever: Retriever | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.db = db
        self.settings = cfg or current_settings()
        self._retriever = retriever
        self._llm = llm

    # ------------------------------------------------------------------ 依赖
    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = get_retriever(self.settings)
        return self._retriever

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = get_llm(self.settings)
        return self._llm

    # ------------------------------------------------------------------ 模型信息
    def model_info(self) -> dict:
        """可选模型与默认参数。"""
        defaults = self.settings.llm.defaults
        return {
            "models": self.llm.model_options
            or [{"value": self.settings.llm.default_model, "label": self.settings.llm.default_model, "description": ""}],
            "defaults": {
                "model": self.settings.llm.default_model,
                "temperature": defaults.temperature,
                "top_p": defaults.top_p,
                "max_tokens": defaults.max_tokens,
                "history_rounds": defaults.history_rounds,
                "retrieval_mode": self.settings.rag.retrieval.mode,
            },
        }

    # ------------------------------------------------------------------ 会话
    def list_sessions(self, user_id: int) -> list[dict]:
        """列出用户的会话，附带知识库名称。"""
        assert self.db is not None
        sessions = self.db.scalars(
            select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        ).all()
        if not sessions:
            return []

        kb_ids: set[int] = set()
        for session in sessions:
            kb_ids.update(session.kb_ids_list)
        name_map: dict[int, str] = {}
        if kb_ids:
            for kb in self.db.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))).all():
                name_map[kb.id] = kb.name

        result = []
        for session in sessions:
            item = session_to_dict(session)
            item["kb_names"] = [name_map[item_id] for item_id in session.kb_ids_list if item_id in name_map]
            result.append(item)
        return result

    def get_session(self, user_id: int, session_id: int) -> ChatSession:
        """获取会话（校验归属）。"""
        assert self.db is not None
        session = self.db.get(ChatSession, session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("会话不存在")
        return session

    def create_session(self, user_id: int, payload) -> ChatSession:
        """新建会话。"""
        assert self.db is not None
        defaults = self.settings.llm.defaults
        session = ChatSession(
            user_id=user_id,
            name=(payload.name or DEFAULT_SESSION_NAME),
            kb_ids=self._validate_kb_ids(user_id, payload.kb_ids or []),
            model=self._resolve_model(payload.model),
            temperature=payload.temperature if payload.temperature is not None else defaults.temperature,
            top_p=payload.top_p if payload.top_p is not None else defaults.top_p,
            max_tokens=payload.max_tokens if payload.max_tokens is not None else defaults.max_tokens,
            history_rounds=payload.history_rounds if payload.history_rounds is not None else defaults.history_rounds,
            retrieval_mode=payload.retrieval_mode or self.settings.rag.retrieval.mode,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        logger.info("创建会话：id=%s user=%s name=%s", session.id, user_id, session.name)
        return session

    def update_session(self, user_id: int, session_id: int, payload) -> ChatSession:
        """更新会话（名称、知识库、模型与推理参数）。"""
        assert self.db is not None
        session = self.get_session(user_id, session_id)

        if payload.name is not None:
            session.name = payload.name
        if payload.kb_ids is not None:
            session.kb_ids = self._validate_kb_ids(user_id, payload.kb_ids)
        if payload.model is not None:
            session.model = self._resolve_model(payload.model, session.model)
        if payload.temperature is not None:
            session.temperature = float(payload.temperature)
        if payload.top_p is not None:
            session.top_p = float(payload.top_p)
        if payload.max_tokens is not None:
            session.max_tokens = int(payload.max_tokens)
        if payload.history_rounds is not None:
            session.history_rounds = int(payload.history_rounds)
        if payload.retrieval_mode is not None:
            session.retrieval_mode = payload.retrieval_mode

        self.db.commit()
        self.db.refresh(session)
        return session

    def delete_session(self, user_id: int, session_id: int) -> None:
        """删除会话及其消息。"""
        assert self.db is not None
        session = self.get_session(user_id, session_id)
        self.db.delete(session)
        self.db.commit()
        logger.info("删除会话：id=%s", session_id)

    def list_messages(self, user_id: int, session_id: int) -> list[ChatMessage]:
        """列出会话消息（按时间正序）。"""
        assert self.db is not None
        session = self.get_session(user_id, session_id)
        return list(
            self.db.scalars(
                select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id.asc())
            ).all()
        )

    def feedback_message(self, user_id: int, message_id: int, feedback: str | None) -> ChatMessage:
        """对助手消息提交反馈（like / dislike / 取消）。"""
        assert self.db is not None
        message = self.db.get(ChatMessage, message_id)
        if message is None:
            raise NotFoundError("消息不存在")
        session = self.db.get(ChatSession, message.session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("消息不存在")
        if message.role != "assistant":
            raise ValidationError("只能对助手的回答提交反馈")

        message.feedback = feedback
        self.db.commit()
        self.db.refresh(message)
        logger.info("更新消息反馈：id=%s feedback=%s", message_id, feedback or "取消")
        return message

    def export_session_markdown(self, user_id: int, session_id: int) -> str:
        """把会话导出为 Markdown 文本（含引用来源与模型参数）。"""
        assert self.db is not None
        session = self.get_session(user_id, session_id)
        messages = list(
            self.db.scalars(
                select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id.asc())
            ).all()
        )

        kb_names = self.kb_names_for(user_id, session.kb_ids_list)
        lines: list[str] = [
            f"# {session.name}",
            "",
            f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 大模型：{session.model}",
            f"- 检索方式：{'混合检索' if session.retrieval_mode == 'hybrid' else '稠密检索'}",
            f"- 关联知识库：{'、'.join(kb_names) if kb_names else '无'}",
            f"- 推理参数：温度 {session.temperature} / topP {session.top_p} / 最长输出 {session.max_tokens} tokens / 历史轮数 {session.history_rounds}",
            "",
            "---",
            "",
        ]
        for message in messages:
            if not message.content:
                continue
            if message.role == "user":
                lines.append(f"## 🧑 用户")
            else:
                lines.append("## 🤖 助手")
            lines.append("")
            lines.append(message.content)
            lines.append("")
            citations = message.citations or []
            if citations:
                lines.append("**引用来源：**")
                lines.append("")
                for citation in citations:
                    page_text = f" 第 {citation.get('page_no')} 页" if citation.get("page_no") else ""
                    lines.append(
                        f"- [{citation.get('index')}] {citation.get('doc_name', '未知文档')}"
                        f"（知识库：{citation.get('kb_name', '未知知识库')}{page_text}，相似度 {citation.get('score', 0):.2f}）"
                    )
                lines.append("")
        return "\n".join(lines).strip() + "\n"

    def kb_names_for(self, user_id: int, kb_ids: Sequence[int]) -> list[str]:
        """按顺序返回知识库名称，忽略不存在或不属于该用户的 ID。"""
        assert self.db is not None
        if not kb_ids:
            return []
        rows = self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(list(kb_ids)), KnowledgeBase.user_id == user_id)
        ).all()
        mapping = {kb.id: kb.name for kb in rows}
        return [mapping[kb_id] for kb_id in kb_ids if kb_id in mapping]

    def ensure_supported_model(self, model: str) -> None:
        """校验模型名是否在配置的可选列表中（路由层提前校验，便于返回 400）。"""
        allowed = self.settings.llm.model_values()
        if allowed and model not in allowed:
            raise ValidationError(f"不支持的大模型「{model}」，可选：{'、'.join(allowed)}")

    def _resolve_model(self, requested: str | None, current: str | None = None) -> str:
        """校验并返回可用模型名。

        - 用户显式选择了不在配置中的模型 → 报错提示可选列表；
        - 会话里保存的是历史模型（如旧版本的 qwen-max）→ 自动回落到默认模型。
        """
        allowed = self.settings.llm.model_values()
        candidate = (requested or current or self.settings.llm.default_model or "").strip()
        if not allowed or candidate in allowed:
            return candidate or self.settings.llm.default_model

        if requested:
            # 用户显式选择了不支持的模型：直接报错（不静默改用其它模型）
            self.ensure_supported_model(requested)

        logger.warning(
            "会话保存的模型「%s」不在可选列表中，自动切换为默认模型「%s」", candidate, self.settings.llm.default_model
        )
        return self.settings.llm.default_model

    def _validate_kb_ids(self, user_id: int, kb_ids: Sequence[int]) -> list[int]:
        """校验知识库归属，过滤无效 ID。"""
        assert self.db is not None
        valid: list[int] = []
        for kb_id in kb_ids or []:
            try:
                kb = self.db.get(KnowledgeBase, int(kb_id))
            except (TypeError, ValueError):
                continue
            if kb is not None and kb.user_id == user_id:
                valid.append(kb.id)
        return valid

    # ------------------------------------------------------------------ 流式问答
    def stream_answer(self, user_id: int, request) -> Iterator[tuple[str, dict]]:
        """流式回答问题，产出 (event, data) 事件。

        事件顺序：start → retrieval → delta… → done（异常时为 error）。
        本方法自行管理数据库会话，避免长连接期间请求级会话被回收。
        """
        if not self.llm.configured:
            yield "error", {
                "message": "未配置 DeepSeek API Key，请在 config.yaml 的 llm.api_key（或环境变量 DEEPSEEK_API_KEY）中填写后重试"
            }
            return

        with session_scope() as db:
            session = db.get(ChatSession, request.session_id)
            if session is None or session.user_id != user_id:
                yield "error", {"message": "会话不存在，请刷新后重试"}
                return

            # ---------------- 参数：请求覆盖 + 持久化 ----------------
            if request.model:
                session.model = self._resolve_model(request.model, session.model)
            if request.temperature is not None:
                session.temperature = float(request.temperature)
            if request.top_p is not None:
                session.top_p = float(request.top_p)
            if request.max_tokens is not None:
                session.max_tokens = int(request.max_tokens)
            if request.history_rounds is not None:
                session.history_rounds = int(request.history_rounds)
            if request.retrieval_mode:
                session.retrieval_mode = request.retrieval_mode
            if request.kb_ids is not None:
                session.kb_ids = [int(item) for item in request.kb_ids]
            db.commit()

            question = request.question.strip()
            kb_ids = session.kb_ids_list
            model = session.model
            temperature = session.temperature
            top_p = session.top_p
            max_tokens = session.max_tokens
            history_rounds = max(0, int(session.history_rounds))
            retrieval_mode = session.retrieval_mode or self.settings.rag.retrieval.mode

            # ---------------- 历史对话 ----------------
            history = self._load_history(db, session.id, history_rounds)

            # ---------------- 落库用户消息 ----------------
            user_message = ChatMessage(session_id=session.id, role="user", content=question, citations=None)
            db.add(user_message)
            db.commit()
            db.refresh(user_message)

            assistant_message = ChatMessage(session_id=session.id, role="assistant", content="", citations=None)
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)

            first_round = not history
            yield "start", {
                "session_id": session.id,
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
            }

            # ---------------- 检索 ----------------
            retrieved: list[RetrievedChunk] = []
            retrieval_warning = ""
            if kb_ids:
                try:
                    query = self._maybe_rewrite(question, model)
                    retrieved = self.retriever.retrieve(
                        query=query,
                        kb_ids=kb_ids,
                        top_k=self.settings.rag.retrieval.top_k,
                        mode=retrieval_mode,
                    )
                except RetrievalError as exc:
                    retrieval_warning = str(exc)
                    logger.warning("检索失败，降级为无上下文回答：%s", exc)
            else:
                retrieval_warning = "未选择知识库"

            citations = self._build_citations(db, retrieved)
            if citations:
                yield "retrieval", {"chunks": citations}

            context_items = [
                ContextItem(
                    index=citation["index"],
                    content=chunk.content,
                    doc_name=citation["doc_name"],
                    kb_name=citation["kb_name"],
                    page_no=citation["page_no"],
                    score=citation["score"],
                )
                for citation, chunk in zip(citations, retrieved)
            ]

            messages = build_messages(
                question=question,
                items=context_items,
                history=history,
                app_name=self.settings.app.name,
                max_chars=self.settings.rag.context.max_chars,
            )

            # ---------------- 流式生成 ----------------
            answer_parts: list[str] = []
            error_message = ""

            def persist_partial() -> None:
                """客户端中断时保存已生成的部分内容，避免留下空白回答。"""
                partial = "".join(answer_parts).strip()
                if not partial:
                    return
                assistant_message.content = partial
                assistant_message.citations = citations or []
                try:
                    db.commit()
                except Exception:  # noqa: BLE001
                    logger.warning("保存部分回答失败", exc_info=True)

            try:
                for delta in self.llm.stream_chat(
                    messages,
                    model=model,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                ):
                    if not delta:
                        continue
                    answer_parts.append(delta)
                    yield "delta", {"content": delta}
            except GeneratorExit:
                logger.info("客户端中断生成，保存已生成内容（%s 字）", len("".join(answer_parts)))
                persist_partial()
                raise
            except LLMError as exc:
                error_message = str(exc)
                logger.error("生成回答失败：%s", error_message)
            except Exception as exc:  # noqa: BLE001
                error_message = f"生成回答时发生异常：{exc}"
                logger.exception("生成回答异常")

            answer = "".join(answer_parts).strip()

            # ---------------- 落库助手消息 ----------------
            assistant_message.content = answer
            assistant_message.citations = citations or []
            if first_round and session.name in ("", DEFAULT_SESSION_NAME):
                session.name = session_title_from_question(question)
            db.commit()

            if error_message:
                yield "error", {"message": error_message, "partial": answer}
                return

            if not answer:
                answer = "抱歉，本次没有生成有效回答，请重试或检查大模型配置。"
                assistant_message.content = answer
                db.commit()

            yield "done", {
                "assistant_message_id": assistant_message.id,
                "answer": answer,
                "finish_reason": "stop",
                "retrieval_warning": retrieval_warning,
                "citation_count": len(citations),
            }

    # ------------------------------------------------------------------ 内部方法
    def _load_history(self, db: Session, session_id: int, rounds: int) -> list[dict]:
        """读取最近 N 轮历史对话（不含当前问题）。"""
        if rounds <= 0:
            return []
        messages = list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id, ChatMessage.content != "")
                .order_by(ChatMessage.id.desc())
                .limit(rounds * 2)
            ).all()
        )
        messages.reverse()
        return [{"role": message.role, "content": message.content} for message in messages if message.content]

    def _maybe_rewrite(self, question: str, model: str) -> str:
        """可选的问题改写：提升检索命中率。"""
        if not self.settings.rag.query_rewrite.enabled:
            return question
        try:
            rewritten = self.llm.complete(
                build_rewrite_messages(question), model=model, temperature=0.1, max_tokens=256
            )
            rewritten = " ".join(rewritten.split())
            if rewritten and len(rewritten) <= 200:
                logger.info("问题改写：%s -> %s", question[:50], rewritten[:80])
                return f"{question} {rewritten}"
        except LLMError as exc:
            logger.warning("问题改写失败，使用原问题：%s", exc)
        return question

    def _build_citations(self, db: Session, chunks: Sequence[RetrievedChunk]) -> list[dict]:
        """补充文档名与知识库名，生成引用信息。"""
        if not chunks:
            return []
        doc_ids = {chunk.doc_id for chunk in chunks}
        kb_ids = {chunk.kb_id for chunk in chunks}
        documents = {
            document.id: document for document in db.scalars(select(Document).where(Document.id.in_(doc_ids))).all()
        }
        knowledge_bases = {
            kb.id: kb for kb in db.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))).all()
        }

        citations: list[dict] = []
        for index, chunk in enumerate(chunks, start=1):
            document = documents.get(chunk.doc_id)
            kb = knowledge_bases.get(chunk.kb_id)
            citations.append(
                {
                    "index": index,
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "doc_name": document.filename if document else "未知文档",
                    "kb_id": chunk.kb_id,
                    "kb_name": kb.name if kb else "未知知识库",
                    "page_no": chunk.page_no,
                    "score": round(float(chunk.score), 4),
                    "preview": chunk.preview(),
                }
            )
        return citations


def session_to_dict(session: ChatSession) -> dict:
    """会话对象转响应字典。"""
    return {
        "id": session.id,
        "name": session.name,
        "kb_ids": session.kb_ids_list,
        "kb_names": [],
        "model": session.model,
        "temperature": session.temperature,
        "top_p": session.top_p,
        "max_tokens": session.max_tokens,
        "history_rounds": session.history_rounds,
        "retrieval_mode": session.retrieval_mode,
        "created_at": format_datetime(session.created_at),
        "updated_at": format_datetime(session.updated_at),
    }


def message_to_dict(message: ChatMessage) -> dict:
    """消息对象转响应字典。"""
    citations = message.citations or []
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": citations,
        "feedback": message.feedback,
        "created_at": format_datetime(message.created_at),
    }


__all__ = ["ChatService", "session_to_dict", "message_to_dict", "DEFAULT_SESSION_NAME"]
