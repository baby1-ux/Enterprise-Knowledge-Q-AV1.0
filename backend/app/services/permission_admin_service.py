"""角色与授权管理服务：角色的增删改、用户角色分配、知识库授权配置。"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.config import Settings, settings as current_settings
from ..core.errors import ForbiddenError, NotFoundError, ValidationError
from ..core.logging import get_logger
from ..db.models import (
    KnowledgeBase,
    KnowledgeBaseMember,
    KnowledgeBaseRole,
    Role,
    User,
    UserRole,
)
from ..schemas.common import format_datetime
from .permission_service import ADMIN_CODE, PermissionService

logger = get_logger("services.permission_admin")


class PermissionAdminService:
    """角色与授权管理（仅管理员可用，由路由层依赖保证）。"""

    def __init__(self, db: Session, cfg: Settings | None = None) -> None:
        self.db = db
        self.settings = cfg or current_settings()

    # ------------------------------------------------------------------ 管理员校验
    @staticmethod
    def ensure_admin(db: Session, user: User) -> None:
        """校验当前用户是否为管理员，非管理员抛 403。"""
        if not PermissionService(db, user).is_admin():
            raise ForbiddenError("仅管理员可执行该操作")

    # ------------------------------------------------------------------ 角色
    def list_roles(self) -> list[dict]:
        """列出全部角色（含用户数与授权知识库数）。"""
        roles = list(self.db.scalars(select(Role).order_by(Role.id.asc())).all())
        result: list[dict] = []
        for role in roles:
            user_count = self.db.scalar(
                select(func.count(UserRole.user_id)).where(UserRole.role_id == role.id)
            ) or 0
            kb_count = self.db.scalar(
                select(func.count(KnowledgeBaseRole.kb_id)).where(KnowledgeBaseRole.role_id == role.id)
            ) or 0
            result.append(
                {
                    "id": role.id,
                    "code": role.code,
                    "name": role.name,
                    "description": role.description or "",
                    "is_system": bool(role.is_system),
                    "user_count": int(user_count),
                    "kb_count": int(kb_count),
                }
            )
        return result

    def create_role(self, code: str, name: str, description: str = "") -> Role:
        """创建自定义角色。"""
        exists = self.db.scalars(select(Role).where(Role.code == code)).first()
        if exists is not None:
            raise ValidationError(f"角色代码已存在：{code}")
        if code == ADMIN_CODE:
            raise ValidationError("admin 为系统内置角色，不可重复创建")
        role = Role(code=code, name=name, description=description or "", is_system=False)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        logger.info("创建角色成功：id=%s code=%s", role.id, role.code)
        return role

    def update_role(self, role_id: int, name: str | None = None, description: str | None = None) -> Role:
        """更新角色名称/说明（内置角色允许改名称，不允许改 code）。"""
        role = self.db.get(Role, role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if name is not None:
            role.name = name.strip() or role.name
        if description is not None:
            role.description = description
        self.db.commit()
        self.db.refresh(role)
        return role

    def delete_role(self, role_id: int) -> None:
        """删除自定义角色（内置角色不可删）。"""
        role = self.db.get(Role, role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.is_system:
            raise ValidationError(f"系统内置角色「{role.name}」不可删除")
        self.db.delete(role)
        self.db.commit()
        logger.info("删除角色成功：id=%s code=%s", role.id, role.code)

    def assign_role_kbs(self, role_id: int, grants: list[dict]) -> int:
        """为角色批量分配知识库（覆盖式：未列出的将被移除）。"""
        role = self.db.get(Role, role_id)
        if role is None:
            raise NotFoundError("角色不存在")

        normalized: list[dict] = []
        for item in grants or []:
            kb_id = int(item["kb_id"])
            kb = self.db.get(KnowledgeBase, kb_id)
            if kb is None:
                raise NotFoundError(f"知识库不存在：{kb_id}")
            normalized.append(
                {
                    "kb_id": kb_id,
                    "can_read": bool(item.get("can_read", True)),
                    "can_write": bool(item.get("can_write", False)),
                }
            )

        # 覆盖式：先清空该角色的旧授权
        self.db.execute(delete(KnowledgeBaseRole).where(KnowledgeBaseRole.role_id == role_id))
        self.db.flush()
        for item in normalized:
            self.db.add(
                KnowledgeBaseRole(
                    kb_id=item["kb_id"],
                    role_id=role_id,
                    can_read=item["can_read"],
                    can_write=item["can_write"],
                )
            )
        self.db.commit()
        logger.info("角色知识库授权更新：role=%s 共 %s 条", role_id, len(normalized))
        return len(normalized)

    # ------------------------------------------------------------------ 用户
    def list_users(self) -> list[dict]:
        """列出全部用户及其角色与知识库数量。"""
        users = list(self.db.scalars(select(User).order_by(User.id.asc())).all())
        result: list[dict] = []
        for user in users:
            perm = PermissionService(self.db, user)
            kb_count = (
                self.db.scalar(
                    select(func.count(KnowledgeBase.id)).where(KnowledgeBase.user_id == user.id)
                )
                or 0
            )
            result.append(
                {
                    "id": user.id,
                    "username": user.username,
                    "roles": perm.role_codes(),
                    "role_names": self._role_names_for(perm.role_codes()),
                    "is_admin": perm.is_admin(),
                    "kb_count": int(kb_count),
                    "created_at": format_datetime(user.created_at),
                }
            )
        return result

    def _role_names_for(self, codes: list[str]) -> list[str]:
        """角色代码 → 角色名列表。"""
        if not codes:
            return []
        rows = self.db.scalars(select(Role).where(Role.code.in_(codes))).all()
        return [role.name for role in rows]

    def assign_user_roles(self, user_id: int, role_ids: list[int]) -> list[str]:
        """为用户分配角色（覆盖式）。"""
        user = self.db.get(User, user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        valid_ids = set(self.db.scalars(select(Role.id)).all())
        cleaned = [int(rid) for rid in (role_ids or []) if int(rid) in valid_ids]
        # 至少保留一个角色，避免出现无任何角色的用户
        if not cleaned:
            raise ValidationError("请至少为用户保留一个角色")

        self.db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        self.db.flush()
        for rid in cleaned:
            self.db.add(UserRole(user_id=user_id, role_id=rid))
        self.db.commit()
        logger.info("用户角色更新：user=%s roles=%s", user_id, cleaned)
        return self._role_names_for(PermissionService(self.db, user).role_codes())

    # ------------------------------------------------------------------ 知识库授权
    def get_kb_permission(self, actor: User, kb_id: int) -> dict:
        """查看知识库的授权明细（所有者或管理员可查看）。"""
        kb = self.db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise NotFoundError("知识库不存在")
        perm = PermissionService(self.db, actor)
        if not perm.is_admin() and kb.user_id != actor.id:
            raise ForbiddenError("仅知识库所有者或管理员可查看授权配置")

        role_rows = self.db.execute(
            select(KnowledgeBaseRole, Role.code, Role.name)
            .join(Role, KnowledgeBaseRole.role_id == Role.id)
            .where(KnowledgeBaseRole.kb_id == kb_id)
            .order_by(Role.id.asc())
        ).all()
        member_rows = self.db.execute(
            select(KnowledgeBaseMember, User.username)
            .join(User, KnowledgeBaseMember.user_id == User.id)
            .where(KnowledgeBaseMember.kb_id == kb_id)
            .order_by(User.id.asc())
        ).all()

        return {
            "kb_id": kb.id,
            "kb_name": kb.name,
            "visibility": kb.visibility,
            "roles": [
                {
                    "role_id": grant.role_id,
                    "role_code": code,
                    "role_name": role_name,
                    "can_read": bool(grant.can_read),
                    "can_write": bool(grant.can_write),
                }
                for grant, code, role_name in role_rows
            ],
            "members": [
                {
                    "user_id": member.user_id,
                    "username": username,
                    "can_read": bool(member.can_read),
                    "can_write": bool(member.can_write),
                }
                for member, username in member_rows
            ],
        }

    def update_kb_permission(
        self,
        actor: User,
        kb_id: int,
        role_grants: list[dict],
        member_grants: list[dict],
    ) -> dict:
        """更新知识库授权（覆盖式：未列出的授权将被移除）。"""
        kb = self.db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise NotFoundError("知识库不存在")
        perm = PermissionService(self.db, actor)
        if not perm.is_admin() and kb.user_id != actor.id:
            raise ForbiddenError("仅知识库所有者或管理员可修改授权配置")

        # ---- 角色授权 ----
        normalized_roles: list[dict] = []
        for item in role_grants or []:
            role_id = int(item["role_id"])
            if self.db.get(Role, role_id) is None:
                raise NotFoundError(f"角色不存在：{role_id}")
            normalized_roles.append(
                {
                    "role_id": role_id,
                    "can_read": bool(item.get("can_read", True)),
                    "can_write": bool(item.get("can_write", False)),
                }
            )

        # ---- 人员直授（排除所有者本人，owner 天然拥有全部权限）----
        normalized_members: list[dict] = []
        for item in member_grants or []:
            user_id = int(item["user_id"])
            target = self.db.get(User, user_id)
            if target is None:
                raise NotFoundError(f"用户不存在：{user_id}")
            if user_id == kb.user_id:
                continue  # 所有者无需授权
            normalized_members.append(
                {
                    "user_id": user_id,
                    "can_read": bool(item.get("can_read", True)),
                    "can_write": bool(item.get("can_write", False)),
                }
            )

        self.db.execute(delete(KnowledgeBaseRole).where(KnowledgeBaseRole.kb_id == kb_id))
        self.db.execute(delete(KnowledgeBaseMember).where(KnowledgeBaseMember.kb_id == kb_id))
        self.db.flush()

        for item in normalized_roles:
            self.db.add(
                KnowledgeBaseRole(kb_id=kb_id, role_id=item["role_id"], can_read=item["can_read"], can_write=item["can_write"])
            )
        for item in normalized_members:
            self.db.add(
                KnowledgeBaseMember(
                    kb_id=kb_id,
                    user_id=item["user_id"],
                    can_read=item["can_read"],
                    can_write=item["can_write"],
                )
            )
        self.db.commit()
        logger.info(
            "知识库授权更新：kb=%s 角色授权 %s 条，人员直授 %s 条",
            kb_id, len(normalized_roles), len(normalized_members),
        )
        return self.get_kb_permission(actor, kb_id)

    def grant_kb_to_role(self, role_id: int, kb_id: int, can_read: bool, can_write: bool) -> None:
        """给角色追加单个知识库授权（角色 → 知识库）。"""
        role = self.db.get(Role, role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if self.db.get(KnowledgeBase, kb_id) is None:
            raise NotFoundError(f"知识库不存在：{kb_id}")
        exists = self.db.scalars(
            select(KnowledgeBaseRole).where(
                KnowledgeBaseRole.role_id == role_id, KnowledgeBaseRole.kb_id == kb_id
            )
        ).first()
        if exists is not None:
            exists.can_read = can_read
            exists.can_write = can_write
        else:
            self.db.add(
                KnowledgeBaseRole(kb_id=kb_id, role_id=role_id, can_read=can_read, can_write=can_write)
            )
        self.db.commit()


__all__ = ["PermissionAdminService"]