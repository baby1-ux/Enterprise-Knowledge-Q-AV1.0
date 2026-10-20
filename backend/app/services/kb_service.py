"""知识库服务：知识库 / 文档 / 分块的增删改查与解析入库流水线。"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import Settings, settings as current_settings
from ..core.errors import AppError, NotFoundError, ValidationError
from ..core.logging import get_logger
from ..db.models import ChatSession, Chunk, Document, KnowledgeBase
from ..db.session import session_scope
from ..schemas.common import format_datetime
from .embedding import EmbeddingError, get_embedder
from .parsing.factory import ParseError, parse_document
from .splitter import TextSplitter
from .vector_store import VectorRecord, VectorStoreError, get_vector_store

logger = get_logger("kb_service")

# 分块向量化的批量大小
_EMBED_BATCH = 8


def _safe_filename(filename: str) -> str:
    """清洗文件名，防止路径穿越。"""
    name = Path(filename or "未命名文件").name
    for char in '\\/:*?"<>|':
        name = name.replace(char, "_")
    name = name.strip() or "未命名文件"
    return name[:120]


class KnowledgeBaseService:
    """知识库相关业务逻辑。"""

    def __init__(self, db: Session | None, cfg: Settings | None = None) -> None:
        self.db = db
        self.settings = cfg or current_settings()

    # ================================================================ 知识库
    def list_knowledge_bases(self, user_id: int) -> list[dict]:
        """列出用户的知识库（含文档数、分块数）。"""
        kbs = self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.user_id == user_id).order_by(KnowledgeBase.id.desc())
        ).all()
        if not kbs:
            return []

        kb_ids = [kb.id for kb in kbs]
        doc_counts = dict(
            self.db.execute(
                select(Document.kb_id, func.count(Document.id))
                .where(Document.kb_id.in_(kb_ids))
                .group_by(Document.kb_id)
            ).all()
        )
        chunk_counts = dict(
            self.db.execute(
                select(Chunk.kb_id, func.count(Chunk.id)).where(Chunk.kb_id.in_(kb_ids)).group_by(Chunk.kb_id)
            ).all()
        )
        return [
            {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "retrieval_mode": kb.retrieval_mode,
                "doc_count": int(doc_counts.get(kb.id, 0)),
                "chunk_count": int(chunk_counts.get(kb.id, 0)),
                "created_at": format_datetime(kb.created_at),
            }
            for kb in kbs
        ]

    def get_knowledge_base(self, user_id: int, kb_id: int) -> KnowledgeBase:
        """获取知识库（校验归属）。"""
        kb = self.db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise NotFoundError("知识库不存在")
        if kb.user_id != user_id:
            raise NotFoundError("知识库不存在")
        return kb

    def create_knowledge_base(self, user_id: int, name: str, description: str = "", retrieval_mode: str = "hybrid") -> KnowledgeBase:
        """创建知识库。"""
        exists = self.db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.user_id == user_id, KnowledgeBase.name == name)
        ).first()
        if exists is not None:
            raise ValidationError(f"已存在同名知识库：{name}")

        kb = KnowledgeBase(
            user_id=user_id,
            name=name,
            description=description or "",
            embedding_model=self.settings.embedding.model,
            embedding_dim=self.settings.embedding.dimension,
            retrieval_mode=retrieval_mode,
        )
        self.db.add(kb)
        self.db.commit()
        self.db.refresh(kb)
        logger.info("创建知识库成功：id=%s name=%s user=%s", kb.id, kb.name, user_id)
        return kb

    def update_knowledge_base(
        self, user_id: int, kb_id: int, name: str | None = None, description: str | None = None, retrieval_mode: str | None = None
    ) -> KnowledgeBase:
        """更新知识库信息。"""
        kb = self.get_knowledge_base(user_id, kb_id)
        if name is not None and name != kb.name:
            duplicated = self.db.scalars(
                select(KnowledgeBase).where(
                    KnowledgeBase.user_id == user_id, KnowledgeBase.name == name, KnowledgeBase.id != kb_id
                )
            ).first()
            if duplicated is not None:
                raise ValidationError(f"已存在同名知识库：{name}")
            kb.name = name
        if description is not None:
            kb.description = description
        if retrieval_mode is not None:
            kb.retrieval_mode = retrieval_mode
        self.db.commit()
        self.db.refresh(kb)
        return kb

    def delete_knowledge_base(self, user_id: int, kb_id: int) -> None:
        """删除知识库（同时清理文档、分块与向量）。"""
        kb = self.get_knowledge_base(user_id, kb_id)
        try:
            get_vector_store(self.settings).delete_by_kb(kb.id)
        except VectorStoreError as exc:  # 向量清理失败不阻塞业务删除
            logger.warning("删除知识库向量失败（已忽略）：%s", exc)

        # 清理引用该知识库的会话配置，避免残留无效 ID
        for session in self.db.scalars(select(ChatSession).where(ChatSession.user_id == user_id)).all():
            kb_ids = session.kb_ids_list
            if kb.id in kb_ids:
                session.kb_ids = [item for item in kb_ids if item != kb.id]

        self.db.delete(kb)
        self.db.commit()
        logger.info("删除知识库成功：id=%s user=%s", kb_id, user_id)

    # ================================================================ 文档
    def document_counts(self, kb_id: int) -> tuple[int, int]:
        """返回 (文档数, 分块数)。"""
        doc_count = self.db.scalar(select(func.count(Document.id)).where(Document.kb_id == kb_id)) or 0
        chunk_count = self.db.scalar(select(func.count(Chunk.id)).where(Chunk.kb_id == kb_id)) or 0
        return int(doc_count), int(chunk_count)

    def list_documents(self, user_id: int, kb_id: int) -> list[Document]:
        """列出知识库下的文档。"""
        self.get_knowledge_base(user_id, kb_id)
        return list(
            self.db.scalars(select(Document).where(Document.kb_id == kb_id).order_by(Document.id.desc())).all()
        )

    def get_document(self, user_id: int, doc_id: int) -> Document:
        """获取文档（校验归属）。"""
        document = self.db.get(Document, doc_id)
        if document is None or document.user_id != user_id:
            raise NotFoundError("文档不存在")
        return document

    def create_document(
        self,
        user_id: int,
        kb_id: int,
        filename: str,
        content: bytes,
        chunk_size: int,
        chunk_overlap: int,
        retrieval_mode: str,
    ) -> Document:
        """保存上传文件并创建文档记录（解析在后台进行）。"""
        kb = self.get_knowledge_base(user_id, kb_id)
        safe_name = _safe_filename(filename)
        suffix = Path(safe_name).suffix.lower()
        allowed = {ext.lower() for ext in self.settings.app.allowed_extensions}
        if suffix not in allowed:
            raise ValidationError(f"不支持的文件类型：{suffix or '未知'}，支持：{'、'.join(sorted(allowed))}")
        if not content:
            raise ValidationError("文件内容为空")
        if len(content) > self.settings.app.max_upload_size_mb * 1024 * 1024:
            raise ValidationError(f"文件过大，最大支持 {self.settings.app.max_upload_size_mb} MB")
        if chunk_overlap >= chunk_size:
            raise ValidationError("重叠大小必须小于切块大小")

        target_dir = self.settings.upload_path / str(user_id) / str(kb.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
        stored_path = target_dir / stored_name
        stored_path.write_bytes(content)

        document = Document(
            kb_id=kb.id,
            user_id=user_id,
            filename=safe_name,
            stored_path=str(stored_path),
            file_type=suffix.lstrip("."),
            size=len(content),
            status="pending",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            retrieval_mode=retrieval_mode,
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        logger.info(
            "文档上传成功：id=%s name=%s size=%s chunk_size=%s overlap=%s mode=%s",
            document.id,
            document.filename,
            document.size,
            chunk_size,
            chunk_overlap,
            retrieval_mode,
        )
        return document

    def reparse_document(self, user_id: int, doc_id: int) -> Document:
        """重置文档状态，等待后台重新解析。"""
        document = self.get_document(user_id, doc_id)
        if not Path(document.stored_path).exists():
            raise ValidationError("原始文件已丢失，请重新上传")
        self._reset_document_data(document)
        document.status = "pending"
        document.error_message = ""
        document.chunk_count = 0
        self.db.commit()
        self.db.refresh(document)
        logger.info("文档已重置，等待重新解析：id=%s", document.id)
        return document

    def delete_document(self, user_id: int, doc_id: int) -> None:
        """删除文档及其分块与向量。"""
        document = self.get_document(user_id, doc_id)
        try:
            get_vector_store(self.settings).delete_by_documents([document.id])
        except VectorStoreError as exc:
            logger.warning("删除文档向量失败（已忽略）：%s", exc)

        path = Path(document.stored_path)
        self.db.delete(document)
        self.db.commit()

        try:
            if path.exists():
                path.unlink()
        except OSError as exc:  # pragma: no cover
            logger.warning("删除本地文件失败：%s", exc)
        logger.info("删除文档成功：id=%s", doc_id)

    def _reset_document_data(self, document: Document) -> None:
        """清空文档的旧分块与向量。"""
        try:
            get_vector_store(self.settings).delete_by_documents([document.id])
        except VectorStoreError as exc:
            logger.warning("清理旧向量失败（已忽略）：%s", exc)
        for chunk in self.db.scalars(select(Chunk).where(Chunk.document_id == document.id)).all():
            self.db.delete(chunk)
        self.db.flush()

    # ================================================================ 分块
    def list_chunks(
        self, user_id: int, doc_id: int, page: int = 1, page_size: int = 10, keyword: str = ""
    ) -> tuple[int, list[Chunk]]:
        """分页查询分块。"""
        document = self.get_document(user_id, doc_id)
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))

        condition = [Chunk.document_id == document.id]
        if keyword:
            condition.append(Chunk.content.like(f"%{keyword.strip()}%"))

        total = self.db.scalar(select(func.count(Chunk.id)).where(*condition)) or 0
        items = list(
            self.db.scalars(
                select(Chunk)
                .where(*condition)
                .order_by(Chunk.chunk_index.asc(), Chunk.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return int(total), items

    def get_chunk(self, user_id: int, chunk_id: int) -> Chunk:
        """获取分块（校验归属）。"""
        chunk = self.db.get(Chunk, chunk_id)
        if chunk is None:
            raise NotFoundError("分块不存在")
        document = self.db.get(Document, chunk.document_id)
        if document is None or document.user_id != user_id:
            raise NotFoundError("分块不存在")
        return chunk

    def update_chunk(self, user_id: int, chunk_id: int, content: str) -> Chunk:
        """编辑分块内容并重新向量化。"""
        chunk = self.get_chunk(user_id, chunk_id)
        chunk.content = content.strip()
        self.db.flush()
        try:
            self._sync_chunk_vector(chunk)
        except (EmbeddingError, VectorStoreError) as exc:
            self.db.rollback()
            raise AppError(f"分块已保存但向量更新失败：{exc}", code=500) from exc
        self.db.commit()
        self.db.refresh(chunk)
        logger.info("更新分块成功：id=%s", chunk_id)
        return chunk

    def set_chunk_enabled(self, user_id: int, chunk_id: int, enabled: bool) -> Chunk:
        """启用/禁用分块（禁用的分块不参与检索）。"""
        chunk = self.get_chunk(user_id, chunk_id)
        chunk.enabled = bool(enabled)
        self.db.flush()
        try:
            self._sync_chunk_vector(chunk)
        except (EmbeddingError, VectorStoreError) as exc:
            self.db.rollback()
            raise AppError(f"分块状态更新失败：{exc}", code=500) from exc
        self.db.commit()
        self.db.refresh(chunk)
        return chunk

    def delete_chunk(self, user_id: int, chunk_id: int) -> None:
        """删除分块及其向量。"""
        chunk = self.get_chunk(user_id, chunk_id)
        document_id = chunk.document_id
        try:
            get_vector_store(self.settings).delete_chunks([chunk.id])
        except VectorStoreError as exc:
            logger.warning("删除分块向量失败（已忽略）：%s", exc)
        self.db.delete(chunk)
        self.db.flush()

        document = self.db.get(Document, document_id)
        if document is not None:
            remain = self.db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == document_id)) or 0
            document.chunk_count = int(remain)
        self.db.commit()
        logger.info("删除分块成功：id=%s", chunk_id)

    def _sync_chunk_vector(self, chunk: Chunk) -> None:
        """重新计算单个分块的向量并写入向量库。"""
        embedder = get_embedder(self.settings)
        store = get_vector_store(self.settings)
        vector = embedder.embed_query(chunk.content)
        store.upsert(
            [
                VectorRecord(
                    chunk_id=chunk.id,
                    kb_id=chunk.kb_id,
                    doc_id=chunk.document_id,
                    content=chunk.content,
                    dense=vector,
                    page_no=chunk.page_no,
                    enabled=chunk.enabled,
                )
            ]
        )

    # ================================================================ 入库流水线
    def ingest_document_sync(self, doc_id: int) -> None:
        """完整执行解析 → 切块 → 向量化（供后台任务调用，使用独立会话）。"""
        started = time.time()
        with session_scope() as db:
            document = db.get(Document, doc_id)
            if document is None:
                logger.warning("解析任务跳过：文档不存在 id=%s", doc_id)
                return
            document.status = "parsing"
            document.error_message = ""
            db.commit()
            kb_id = document.kb_id
            chunk_size = document.chunk_size
            chunk_overlap = document.chunk_overlap
            path = Path(document.stored_path)

        logger.info("开始解析文档：id=%s kb=%s path=%s", doc_id, kb_id, path)
        try:
            blocks = parse_document(path, self.settings)
            splitter = TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks = splitter.split_blocks(blocks)
            if not chunks:
                raise ParseError("切块结果为空，请检查文档内容或调整切块参数")

            embedder = get_embedder(self.settings)
            store = get_vector_store(self.settings)

            texts = [chunk.content for chunk in chunks]
            vectors: list[list[float]] = []
            for start in range(0, len(texts), _EMBED_BATCH):
                vectors.extend(embedder.embed_documents(texts[start : start + _EMBED_BATCH]))

            if len(vectors) != len(chunks):
                raise AppError("向量数量与分块数量不一致，请重试", code=500)

            with session_scope() as db:
                document = db.get(Document, doc_id)
                if document is None:
                    raise AppError("文档已被删除，解析中止", code=404)

                # 清理旧数据（重新解析场景）
                try:
                    store.delete_by_documents([doc_id])
                except VectorStoreError as exc:
                    logger.warning("清理旧向量失败（已忽略）：%s", exc)
                for old in db.scalars(select(Chunk).where(Chunk.document_id == doc_id)).all():
                    db.delete(old)
                db.flush()

                records: list[VectorRecord] = []
                for chunk, vector in zip(chunks, vectors):
                    entity = Chunk(
                        document_id=doc_id,
                        kb_id=document.kb_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        page_no=chunk.page_no,
                        enabled=True,
                    )
                    db.add(entity)
                    db.flush()
                    records.append(
                        VectorRecord(
                            chunk_id=entity.id,
                            kb_id=document.kb_id,
                            doc_id=doc_id,
                            content=chunk.content,
                            dense=vector,
                            page_no=chunk.page_no,
                            enabled=True,
                        )
                    )

                store.upsert(records)

                document.status = "success"
                document.chunk_count = len(records)
                document.error_message = ""
                db.commit()

            logger.info(
                "文档解析完成：id=%s 分块数=%s 耗时=%.2fs",
                doc_id,
                len(chunks),
                time.time() - started,
            )
        except Exception as exc:  # noqa: BLE001 - 任何异常都要落库为失败状态
            message = str(exc) or exc.__class__.__name__
            logger.exception("文档解析失败：id=%s 原因=%s", doc_id, message)
            with session_scope() as db:
                document = db.get(Document, doc_id)
                if document is not None:
                    document.status = "failed"
                    document.error_message = message[:1000]
                    db.commit()


def document_to_dict(document: Document) -> dict:
    """文档对象转响应字典。"""
    return {
        "id": document.id,
        "kb_id": document.kb_id,
        "filename": document.filename,
        "file_type": document.file_type,
        "size": document.size,
        "status": document.status,
        "error_message": document.error_message or "",
        "chunk_count": document.chunk_count,
        "chunk_size": document.chunk_size,
        "chunk_overlap": document.chunk_overlap,
        "retrieval_mode": document.retrieval_mode,
        "created_at": format_datetime(document.created_at),
    }


def chunk_to_dict(chunk: Chunk) -> dict:
    """分块对象转响应字典。"""
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "page_no": chunk.page_no,
        "enabled": bool(chunk.enabled),
        "created_at": format_datetime(chunk.created_at),
    }


def knowledge_base_to_dict(kb: KnowledgeBase, doc_count: int = 0, chunk_count: int = 0) -> dict:
    """知识库对象转响应字典。"""
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description or "",
        "retrieval_mode": kb.retrieval_mode,
        "doc_count": doc_count,
        "chunk_count": chunk_count,
        "created_at": format_datetime(kb.created_at),
    }


def ingest_documents(doc_ids: Sequence[int], cfg: Settings | None = None) -> None:
    """批量解析入库（顺序执行，便于控制资源占用）。"""
    service = KnowledgeBaseService(db=None, cfg=cfg)
    for doc_id in doc_ids:
        service.ingest_document_sync(doc_id)
