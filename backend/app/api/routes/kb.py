"""知识库接口：知识库管理、文档上传解析、分块预览编辑（已接入 RBAC）。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile

from ...core.config import Settings
from ...core.errors import ValidationError
from ...core.logging import get_logger
from ...db.models import User
from ...schemas.kb import (
    BatchUploadOut,
    ChunkEnabledUpdate,
    ChunkOut,
    ChunkPageOut,
    ChunkUpdate,
    DocumentOut,
    DocumentStatusOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    SearchChunkOut,
)
from ...services.kb_service import (
    KnowledgeBaseService,
    chunk_to_dict,
    document_to_dict,
    ingest_documents,
    knowledge_base_to_dict,
)
from ..deps import get_current_user, get_kb_service, get_settings_dep
from ..helpers import dump, ok

router = APIRouter(prefix="/kb", tags=["知识库"])
logger = get_logger("api.kb")


# ============================================================ 知识库
@router.get("", summary="知识库列表")
@router.get("/", summary="知识库列表")
def list_knowledge_bases(
    keyword: str = Query("", description="按知识库名称模糊搜索"),
    current_user: User = Depends(get_current_user),  # noqa: ARG001 - 显式声明用于鉴权提示
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """列出当前用户可访问的全部知识库（own + 角色授权 + 公开）。"""
    items = service.list_knowledge_bases(keyword=keyword)
    return ok([dump(KnowledgeBaseOut(**item)) for item in items])


@router.post("", summary="创建知识库")
@router.post("/", summary="创建知识库")
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """新建知识库（所有者 = 当前用户）。"""
    kb = service.create_knowledge_base(
        name=payload.name,
        description=payload.description,
        retrieval_mode=payload.retrieval_mode,
        visibility=getattr(payload, "visibility", "private") or "private",
    )
    doc_count, chunk_count = service.document_counts(kb.id)
    payload_dict = knowledge_base_to_dict(
        kb, doc_count, chunk_count, can_write=True, access_type="owner", owner_id=kb.user_id
    )
    return ok(dump(KnowledgeBaseOut(**payload_dict)), "创建成功")


@router.put("/{kb_id}", summary="更新知识库")
def update_knowledge_base(
    kb_id: int,
    payload: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """修改知识库名称/描述/默认检索方式/可见范围。"""
    kb = service.update_knowledge_base(
        kb_id=kb_id,
        name=payload.name,
        description=payload.description,
        retrieval_mode=payload.retrieval_mode,
        visibility=getattr(payload, "visibility", None),
    )
    doc_count, chunk_count = service.document_counts(kb.id)
    payload_dict = knowledge_base_to_dict(
        kb, doc_count, chunk_count, can_write=True, access_type="owner", owner_id=kb.user_id
    )
    return ok(dump(KnowledgeBaseOut(**payload_dict)), "更新成功")


@router.delete("/{kb_id}", summary="删除知识库")
def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """删除知识库及其全部文档与向量（需可写权限）。"""
    service.delete_knowledge_base(kb_id)
    return ok({"deleted": True}, "删除成功")


# ============================================================ 文档
@router.get("/{kb_id}/documents", summary="文档列表")
def list_documents(
    kb_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """列出知识库下的文档及解析状态。"""
    documents = service.list_documents(kb_id)
    return ok([dump(DocumentOut(**document_to_dict(document))) for document in documents])


@router.post("/{kb_id}/documents", summary="上传并解析文档")
async def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="待解析的文件"),
    chunk_size: int = Form(500, description="切块大小"),
    chunk_overlap: int = Form(50, description="重叠大小"),
    retrieval_mode: str = Form("hybrid", description="dense / hybrid"),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
    cfg: Settings = Depends(get_settings_dep),
) -> dict:
    """上传文档，后台自动解析、切块并写入向量库。"""
    if chunk_size < 100 or chunk_size > 2000:
        raise ValidationError("切块大小需在 100~2000 之间")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValidationError("重叠大小需大于等于 0 且小于切块大小")
    if retrieval_mode not in ("dense", "hybrid"):
        raise ValidationError("检索方式仅支持 dense 或 hybrid")

    content = await file.read()
    document = service.create_document(
        kb_id=kb_id,
        filename=file.filename or "未命名文件",
        content=content,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        retrieval_mode=retrieval_mode,
    )
    background_tasks.add_task(ingest_documents, [document.id], cfg)
    logger.info("文档已加入解析队列：id=%s filename=%s", document.id, document.filename)
    return ok(dump(DocumentOut(**document_to_dict(document))), "上传成功，正在后台解析")


@router.post("/{kb_id}/documents/batch", summary="批量上传并解析文档")
async def upload_documents_batch(
    kb_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description="待解析的多个文件"),
    chunk_size: int = Form(500, description="切块大小"),
    chunk_overlap: int = Form(50, description="重叠大小"),
    retrieval_mode: str = Form("hybrid", description="dense / hybrid"),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
    cfg: Settings = Depends(get_settings_dep),
) -> dict:
    """批量上传文档（单次最多 20 个），后台统一解析；单个文件失败不影响其它文件。"""
    if chunk_size < 100 or chunk_size > 2000:
        raise ValidationError("切块大小需在 100~2000 之间")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValidationError("重叠大小需大于等于 0 且小于切块大小")
    if retrieval_mode not in ("dense", "hybrid"):
        raise ValidationError("检索方式仅支持 dense 或 hybrid")
    if not files:
        raise ValidationError("请至少选择一个文件")
    if len(files) > 20:
        raise ValidationError("单次最多上传 20 个文件，请分批上传")

    file_payloads: list[tuple[str, bytes]] = []
    for upload in files:
        content = await upload.read()
        file_payloads.append((upload.filename or "未命名文件", content))

    created, failures = service.create_documents_batch(
        kb_id=kb_id,
        files=file_payloads,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        retrieval_mode=retrieval_mode,
    )
    if created:
        background_tasks.add_task(ingest_documents, [document.id for document in created], cfg)
        logger.info("批量上传 %s 个文件已加入解析队列：kb=%s", len(created), kb_id)

    return ok(
        dump(
            BatchUploadOut(
                uploaded=[DocumentOut(**document_to_dict(document)) for document in created],
                failed=[item for item in failures],
            )
        ),
        f"上传完成：成功 {len(created)} 个，失败 {len(failures)} 个",
    )


@router.get("/documents/{doc_id}/status", summary="解析进度")
def get_document_status(
    doc_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """查询文档解析状态，供前端轮询。"""
    document = service.get_document(doc_id)
    data = DocumentStatusOut(
        id=document.id,
        status=document.status,
        chunk_count=document.chunk_count,
        error_message=document.error_message or "",
    )
    return ok(dump(data))


@router.post("/documents/{doc_id}/reparse", summary="重新解析文档")
def reparse_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
    cfg: Settings = Depends(get_settings_dep),
) -> dict:
    """清空旧分块并重新解析文档。"""
    document = service.reparse_document(doc_id)
    background_tasks.add_task(ingest_documents, [document.id], cfg)
    return ok(dump(DocumentOut(**document_to_dict(document))), "已开始重新解析")


@router.delete("/documents/{doc_id}", summary="删除文档")
def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """删除文档及其分块与向量。"""
    service.delete_document(doc_id)
    return ok({"deleted": True}, "删除成功")


# ============================================================ 分块
@router.get("/documents/{doc_id}/chunks", summary="分块分页列表")
def list_chunks(
    doc_id: int,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    keyword: str = Query("", description="内容关键字"),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """分页查看文档分块，支持关键字检索。"""
    total, chunks = service.list_chunks(doc_id, page=page, page_size=page_size, keyword=keyword)
    data = ChunkPageOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[ChunkOut(**chunk_to_dict(chunk)) for chunk in chunks],
    )
    return ok(dump(data))


@router.get("/chunks/search", summary="跨库搜索分块")
def search_chunks(
    keyword: str = Query(..., min_length=1, description="分块内容关键字"),
    kb_ids: list[int] = Query(default=[], description="限定的知识库 ID（仅在用户可访问范围内生效）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """按内容关键字跨知识库搜索分块（带文档名与知识库名）。"""
    total, items = service.search_chunks_all(
        keyword, kb_ids=kb_ids, page=page, page_size=page_size
    )
    return ok({"total": total, "page": page, "page_size": page_size, "items": [dump(SearchChunkOut(**item)) for item in items]})


@router.put("/chunks/{chunk_id}", summary="编辑分块")
def update_chunk(
    chunk_id: int,
    payload: ChunkUpdate,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """修改分块内容并重新向量化。"""
    chunk = service.update_chunk(chunk_id, payload.content)
    return ok(dump(ChunkOut(**chunk_to_dict(chunk))), "保存成功")


@router.put("/chunks/{chunk_id}/enabled", summary="启停分块")
def set_chunk_enabled(
    chunk_id: int,
    payload: ChunkEnabledUpdate,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """启用或禁用分块（禁用后不参与检索）。"""
    chunk = service.set_chunk_enabled(chunk_id, payload.enabled)
    return ok(dump(ChunkOut(**chunk_to_dict(chunk))), "已更新")


@router.delete("/chunks/{chunk_id}", summary="删除分块")
def delete_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    service: KnowledgeBaseService = Depends(get_kb_service),
) -> dict:
    """删除分块及其向量。"""
    service.delete_chunk(chunk_id)
    return ok({"deleted": True}, "删除成功")
