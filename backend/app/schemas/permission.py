"""角色与权限管理相关的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RoleCreate(BaseModel):
    """创建角色。"""

    code: str = Field(..., min_length=2, max_length=32, description="角色代码（英文小写，如 sales）")
    name: str = Field(..., min_length=1, max_length=64, description="角色名称")
    description: str = Field("", max_length=255, description="角色说明")

    @field_validator("code")
    @classmethod
    def check_code(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.replace("_", "").isalnum():
            raise ValueError("角色代码仅支持英文、数字与下划线")
        return value

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("角色名称不能为空")
        return value


class RoleOut(BaseModel):
    """角色信息。"""

    id: int
    code: str
    name: str
    description: str = ""
    is_system: bool = False
    user_count: int = 0
    kb_count: int = 0


class RoleKbsUpdate(BaseModel):
    """为角色批量分配知识库（读/写权限位）。"""

    grants: list[dict] = Field(default_factory=list, description="[{kb_id, can_read, can_write}]，未列出的知识库将被移除")

    @field_validator("grants")
    @classmethod
    def check_grants(cls, value: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for item in value:
            if not isinstance(item, dict) or "kb_id" not in item:
                raise ValueError("grants 每项必须包含 kb_id")
            normalized.append(
                {
                    "kb_id": int(item["kb_id"]),
                    "can_read": bool(item.get("can_read", True)),
                    "can_write": bool(item.get("can_write", False)),
                }
            )
        return normalized


class UserRolesUpdate(BaseModel):
    """为用户分配角色（覆盖式）。"""

    role_ids: list[int] = Field(default_factory=list, description="角色 ID 列表（覆盖原有分配）")


class UserListItem(BaseModel):
    """用户列表项（含角色）。"""

    id: int
    username: str
    roles: list[str] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)
    is_admin: bool = False
    kb_count: int = 0
    created_at: str | None = None


class KbPermissionItem(BaseModel):
    """单个知识库的授权明细。"""

    kb_id: int
    kb_name: str = ""
    can_read: bool = True
    can_write: bool = False


class KbPermissionOut(BaseModel):
    """知识库授权总览（所有者视角）。"""

    kb_id: int
    kb_name: str = ""
    visibility: str = "private"
    roles: list[dict] = Field(default_factory=list, description="[{role_id, role_code, role_name, can_read, can_write}]")
    members: list[dict] = Field(default_factory=list, description="[{user_id, username, can_read, can_write}]")


class KbPermissionUpdate(BaseModel):
    """更新知识库授权。"""

    role_grants: list[dict] = Field(default_factory=list, description="[{role_id, can_read, can_write}]")
    member_grants: list[dict] = Field(default_factory=list, description="[{user_id, can_read, can_write}]")


__all__ = [
    "RoleCreate",
    "RoleOut",
    "RoleKbsUpdate",
    "UserRolesUpdate",
    "UserListItem",
    "KbPermissionItem",
    "KbPermissionOut",
    "KbPermissionUpdate",
]