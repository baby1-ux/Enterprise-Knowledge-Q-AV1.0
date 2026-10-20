/** 角色与知识库授权管理接口（仅 admin 可访问）。 */

import { http } from './request'

/* ---------------- 角色 ---------------- */

/** 角色列表 */
export function listRoles() {
  return http.get('/admin/roles')
}

/** 创建角色 */
export function createRole({ code, name, description }) {
  return http.post('/admin/roles', { code, name, description: description || '' })
}

/** 更新角色 */
export function updateRole(roleId, { name, description }) {
  return http.put(`/admin/roles/${roleId}`, { name, description: description || '' })
}

/** 删除角色 */
export function deleteRole(roleId) {
  return http.del(`/admin/roles/${roleId}`)
}

/** 给角色分配知识库（覆盖式） */
export function assignRoleKbs(roleId, grants) {
  return http.put(`/admin/roles/${roleId}/kbs`, { grants })
}

/* ---------------- 用户角色分配 ---------------- */

/** 用户列表（含角色） */
export function listUsers() {
  return http.get('/admin/users')
}

/** 为用户分配角色（覆盖式） */
export function assignUserRoles(userId, roleIds) {
  return http.put(`/admin/users/${userId}/roles`, { role_ids: roleIds })
}

/* ---------------- 知识库授权 ---------------- */

/** 查看知识库授权（所有者或 admin） */
export function getKbPermission(kbId) {
  return http.get(`/admin/kb/${kbId}/permission`)
}

/** 更新知识库授权（覆盖式） */
export function updateKbPermission(kbId, roleGrants, memberGrants) {
  return http.put(`/admin/kb/${kbId}/permission`, {
    role_grants: roleGrants,
    member_grants: memberGrants
  })
}
