"""权限解析服务：根据当前用户身份返回对知识库 / 文档 / 分块的访问能力。

所有路由层都通过 PermissionService 集中判断权限，避免散落在 service 各处的 user_id 硬编码。
解析结果在请求级缓存（self._xxx 字段），单次请求多次复用，无 N+1 问题。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..core.errors import ForbiddenError
from ..core.logging import get_logger
from ..db.models import (
    KnowledgeBase,
    KnowledgeBaseMember,
    KnowledgeBaseRole,
    Role,
    User,
    UserRole,
)

logger = get_logger("services.permission")

ADMIN_CODE = "admin"
PRIVATE_VIS = "private"
ROLE_VIS = "role"
ALL_VIS = "all"


class PermissionService:
    """当前用户对知识库的访问权限解析（请求级缓存）。"""

    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user
        self._role_ids_cache: set[int] | None = None
        self._is_admin_cache: bool | None = None
        self._accessible_kb_ids_cache: set[int] | None = None
        self._accessible_kb_query_cache: Any = None

    # ------------------------------------------------------------------ 基础查询
    def _role_ids(self) -> set[int]:
        """当前用户拥有的所有角色 ID（含 admin 标识）。"""
        if self._role_ids_cache is None:
            rows = self.db.execute(
                select(UserRole.role_id).where(UserRole.user_id == self.user.id)
            ).all()
            self._role_ids_cache = {int(row[0]) for row in rows}
        return self._role_ids_cache

    def role_codes(self) -> list[str]:
        """当前用户拥有的角色代码（用于返回前端）。"""
        ids = self._role_ids()
        if not ids:
            return []
        codes = self.db.scalars(select(Role.code).where(Role.id.in_(ids))).all()
        return sorted({str(code) for code in codes})

    def is_admin(self) -> bool:
        """是否管理员角色（拥有全部 KB 的读写权限）。"""
        if self._is_admin_cache is None:
            self._is_admin_cache = self.db.scalar(
                select(func.count(Role.id))
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == self.user.id, Role.code == ADMIN_CODE)
            ) or 0
            self._is_admin_cache = bool(self._is_admin_cache)
        return self._is_admin_cache

    # ------------------------------------------------------------------ 列表解析
    def accessible_kb_ids(self) -> set[int]:
        """返回当前用户可访问的全部知识库 ID（含 own + 角色授权 + 人员直授 + visibility=all）。"""
        if self._accessible_kb_ids_cache is not None:
            return self._accessible_kb_ids_cache
        if self.is_admin():
            ids = set(
                int(value) for value in self.db.scalars(select(KnowledgeBase.id)).all()
            )
            self._accessible_kb_ids_cache = ids
            return ids

        role_ids = self._role_ids()
        conditions = [
            KnowledgeBase.user_id == self.user.id,
            KnowledgeBase.visibility == ALL_VIS,
        ]
        if role_ids:
            conditions.append(
                and_(
                    KnowledgeBase.visibility == ROLE_VIS,
                    KnowledgeBase.id.in_(
                        select(KnowledgeBaseRole.kb_id).where(
                            KnowledgeBaseRole.role_id.in_(role_ids)
                        )
                    ),
                )
            )
        conditions.append(
            KnowledgeBase.id.in_(
                select(KnowledgeBaseMember.kb_id).where(
                    KnowledgeBaseMember.user_id == self.user.id
                )
            )
        )
        rows = self.db.execute(
            select(KnowledgeBase.id).where(or_(*conditions))
        ).all()
        self._accessible_kb_ids_cache = {int(row[0]) for row in rows}
        return self._accessible_kb_ids_cache

    def accessible_kb_query(self):
        """生成 KnowledgeBase 列表查询的 where 条件（直接挂到现有查询上）。"""
        if self._accessible_kb_query_cache is not None:
            return self._accessible_kb_query_cache
        if self.is_admin():
            # admin 走旁路：所有 KB
            from sqlalchemy import true

            self._accessible_kb_query_cache = true()
            return self._accessible_kb_query_cache
        role_ids = self._role_ids()
        conditions = [
            KnowledgeBase.user_id == self.user.id,
            KnowledgeBase.visibility == ALL_VIS,
        ]
        if role_ids:
            conditions.append(
                and_(
                    KnowledgeBase.visibility == ROLE_VIS,
                    KnowledgeBase.id.in_(
                        select(KnowledgeBaseRole.kb_id).where(
                            KnowledgeBaseRole.role_id.in_(role_ids)
                        )
                    ),
                )
            )
        conditions.append(
            KnowledgeBase.id.in_(
                select(KnowledgeBaseMember.kb_id).where(
                    KnowledgeBaseMember.user_id == self.user.id
                )
            )
        )
        self._accessible_kb_query_cache = or_(*conditions)
        return self._accessible_kb_query_cache

    # ------------------------------------------------------------------ 单 KB 判断
    def can_read(self, kb: KnowledgeBase) -> bool:
        """是否有权读取（检索 / 查看文档 / 引用）。"""
        if self.is_admin() or kb.user_id == self.user.id:
            return True
        if kb.visibility == ALL_VIS:
            return True
        if kb.visibility == ROLE_VIS:
            role_ids = self._role_ids()
            if not role_ids:
                return False
            granted = (
                self.db.scalar(
                    select(func.count(KnowledgeBaseRole.kb_id)).where(
                        KnowledgeBaseRole.kb_id == kb.id,
                        KnowledgeBaseRole.role_id.in_(role_ids),
                        KnowledgeBaseRole.can_read.is_(True),
                    )
                )
                or 0
            )
            if granted:
                return True
        return self._member_can(kb, "can_read")

    def can_write(self, kb: KnowledgeBase) -> bool:
        """是否有权管理（上传文档 / 编辑 / 删除 KB 与文档 / 编辑分块 / 启停分块）。"""
        if self.is_admin() or kb.user_id == self.user.id:
            return True
        role_ids = self._role_ids()
        if role_ids:
            granted = (
                self.db.scalar(
                    select(func.count(KnowledgeBaseRole.kb_id)).where(
                        KnowledgeBaseRole.kb_id == kb.id,
                        KnowledgeBaseRole.role_id.in_(role_ids),
                        KnowledgeBaseRole.can_write.is_(True),
                    )
                )
                or 0
            )
            if granted:
                return True
        return self._member_can(kb, "can_write")

    def _member_can(self, kb: KnowledgeBase, action: str) -> bool:
        return bool(
            self.db.scalar(
                select(func.count(KnowledgeBaseMember.kb_id)).where(
                    KnowledgeBaseMember.kb_id == kb.id,
                    KnowledgeBaseMember.user_id == self.user.id,
                    getattr(KnowledgeBaseMember, action).is_(True),
                )
            )
            or 0
        )

    def should_404(self, kb: KnowledgeBase) -> bool:
        """访问失败时应该返回 404（私有 KB 防存在性探测）还是 403。"""
        # 私有 KB + 非所有者 → 404（不暴露存在性）
        # 其它（公开 / 角色共享）但无权限 → 403（用户知道这个库存在）
        return kb.user_id != self.user.id and kb.visibility == PRIVATE_VIS

    def assert_can_read(self, kb: KnowledgeBase) -> None:
        if not self.can_read(kb):
            if self.should_404(kb):
                from ..core.errors import NotFoundError

                raise NotFoundError("知识库不存在")
            raise ForbiddenError(f"无权访问知识库「{kb.name}」")

    def assert_can_write(self, kb: KnowledgeBase) -> None:
        if not self.can_write(kb):
            if self.should_404(kb):
                from ..core.errors import NotFoundError

                raise NotFoundError("知识库不存在")
            raise ForbiddenError(f"对知识库「{kb.name}」仅有只读权限或无权访问")

    # ------------------------------------------------------------------ 路径内校验
    def filter_readable_kb_ids(self, kb_ids) -> list[int]:
        """过滤出用户真正能读的知识库 ID（用于会话 / 流式问答防御）。"""
        if not kb_ids:
            return []
        accessible = self.accessible_kb_ids()
        result: list[int] = []
        for item in kb_ids or []:
            try:
                kid = int(item)
            except (TypeError, ValueError):
                continue
            if kid in accessible:
                result.append(kid)
        return result
