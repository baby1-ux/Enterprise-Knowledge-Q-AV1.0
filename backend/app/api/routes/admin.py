"""管理员接口：角色管理、用户角色分配、知识库授权配置（仅 admin 可访问）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import ForbiddenError
from ...core.logging import get_logger
from ...db.models import User
from ...db.session import get_db
from ...schemas.permission import (
    KbPermissionOut,
    KbPermissionUpdate,
    RoleCreate,
    RoleKbsUpdate,
    RoleOut,
    UserListItem,
    UserRolesUpdate,
)
from ...services.permission_admin_service import PermissionAdminService
from ..deps import get_current_user, get_settings_dep
from ..helpers import dump, ok

router = APIRouter(prefix="/admin", tags=["管理员"])
logger = get_logger("api.admin")


def get_admin_service(
    db: Session = Depends(get_db), cfg: Settings = Depends(get_settings_dep)
) -> PermissionAdminService:
    """管理员服务（构造时即校验 admin 身份）。"""
    return PermissionAdminService(db, cfg)


def require_admin(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """路由级管理员守卫：非 admin 直接 403。"""
    PermissionAdminService.ensure_admin(db, current_user)
    return current_user


# ============================================================ 角色
@router.get("/roles", summary="角色列表")
def list_roles(
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """列出全部角色（含用户数与授权知识库数）。"""
    return ok([dump(RoleOut(**item)) for item in service.list_roles()])


@router.post("/roles", summary="创建角色")
def create_role(
    payload: RoleCreate,
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """创建自定义角色。"""
    role = service.create_role(payload.code, payload.name, payload.description)
    data = {"id": role.id, "code": role.code, "name": role.name, "description": role.description, "is_system": role.is_system, "user_count": 0, "kb_count": 0}
    return ok(dump(RoleOut(**data)), "创建成功")


@router.put("/roles/{role_id}", summary="更新角色")
def update_role(
    role_id: int,
    payload: RoleCreate,
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """更新角色名称/说明（code 不可变）。"""
    role = service.update_role(role_id, payload.name, payload.description)
    data = {"id": role.id, "code": role.code, "name": role.name, "description": role.description, "is_system": role.is_system}
    return ok(dump(RoleOut(**data)), "更新成功")


@router.delete("/roles/{role_id}", summary="删除角色")
def delete_role(
    role_id: int,
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """删除自定义角色（内置角色不可删）。"""
    service.delete_role(role_id)
    return ok({"deleted": True}, "删除成功")


@router.put("/roles/{role_id}/kbs", summary="为角色分配知识库")
def assign_role_kbs(
    role_id: int,
    payload: RoleKbsUpdate,
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """为角色批量分配知识库（覆盖式）。"""
    count = service.assign_role_kbs(role_id, payload.grants)
    return ok({"role_id": role_id, "granted": count}, f"已更新角色授权（{count} 条）")


# ============================================================ 用户
@router.get("/users", summary="用户列表")
def list_users(
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """列出全部用户及其角色。"""
    return ok([dump(UserListItem(**item)) for item in service.list_users()])


@router.put("/users/{user_id}/roles", summary="为用户分配角色")
def assign_user_roles(
    user_id: int,
    payload: UserRolesUpdate,
    current_user: User = Depends(require_admin),  # noqa: ARG001
    service: PermissionAdminService = Depends(get_admin_service),
) -> dict:
    """为用户分配角色（覆盖式，至少保留一个角色）。"""
    names = service.assign_user_roles(user_id, payload.role_ids)
    return ok({"user_id": user_id, "role_names": names}, "角色已更新")


# ============================================================ 知识库授权
@router.get("/kb/{kb_id}/permission", summary="查看知识库授权")
def get_kb_permission(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cfg: Settings = Depends(get_settings_dep),
) -> dict:
    """查看知识库的授权明细（所有者或管理员）。"""
    svc = PermissionAdminService(db, cfg)
    return ok(dump(KbPermissionOut(**svc.get_kb_permission(current_user, kb_id))))


@router.put("/kb/{kb_id}/permission", summary="更新知识库授权")
def update_kb_permission(
    kb_id: int,
    payload: KbPermissionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cfg: Settings = Depends(get_settings_dep),
) -> dict:
    """更新知识库的角色授权与人员直授（覆盖式）。"""
    svc = PermissionAdminService(db, cfg)
    result = svc.update_kb_permission(
        current_user, kb_id, payload.role_grants, payload.member_grants
    )
    return ok(dump(KbPermissionOut(**result)), "授权已更新")


__all__ = ["router", "require_admin", "get_admin_service"]