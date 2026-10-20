<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  assignRoleKbs,
  assignUserRoles,
  createRole,
  deleteRole,
  listRoles,
  listUsers,
  updateRole
} from '@/api/permission'

const router = useRouter()
const auth = useAuthStore()

const activeTab = ref('roles')

const roles = ref([])
const users = ref([])
const loading = ref(false)

/* ---------- 角色 ---------- */
const roleDialogVisible = ref(false)
const roleEditingId = ref(null)
const roleFormRef = ref(null)
const roleForm = reactive({ code: '', name: '', description: '' })

const roleRules = {
  code: [
    { required: true, message: '请输入角色代码', trigger: 'blur' },
    { min: 2, max: 32, message: '角色代码 2~32 个字符', trigger: 'blur' }
  ],
  name: [
    { required: true, message: '请输入角色名', trigger: 'blur' },
    { max: 64, message: '角色名不超过 64 字符', trigger: 'blur' }
  ],
  description: [{ max: 255, message: '说明不超过 255 字符', trigger: 'blur' }]
}

async function loadRoles() {
  loading.value = true
  try {
    const data = await listRoles()
    roles.value = Array.isArray(data) ? data : []
  } catch (error) {
    ElMessage.error(error?.message || '角色列表加载失败')
  } finally {
    loading.value = false
  }
}

function openCreateRole() {
  roleEditingId.value = null
  Object.assign(roleForm, { code: '', name: '', description: '' })
  roleDialogVisible.value = true
  roleFormRef.value?.clearValidate()
}

function openEditRole(role) {
  if (role.is_system) {
    ElMessage.warning('系统内置角色不可编辑（仅可修改名称/说明）')
  }
  roleEditingId.value = role.id
  Object.assign(roleForm, {
    code: role.code,
    name: role.name,
    description: role.description || ''
  })
  roleDialogVisible.value = true
  roleFormRef.value?.clearValidate()
}

async function submitRole() {
  const valid = await roleFormRef.value?.validate().catch(() => false)
  if (!valid) return
  try {
    if (roleEditingId.value) {
      await updateRole(roleEditingId.value, { name: roleForm.name, description: roleForm.description })
      ElMessage.success('角色已更新')
    } else {
      await createRole({ code: roleForm.code, name: roleForm.name, description: roleForm.description })
      ElMessage.success('角色已创建')
    }
    roleDialogVisible.value = false
    await loadRoles()
  } catch (error) {
    ElMessage.error(error?.message || '保存失败')
  }
}

async function removeRole(role) {
  if (role.is_system) {
    ElMessage.warning('系统内置角色不可删除')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定删除角色「${role.name}」吗？`,
      '删除角色',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await deleteRole(role.id)
    ElMessage.success('角色已删除')
    await loadRoles()
  } catch (error) {
    ElMessage.error(error?.message || '删除失败')
  }
}

/** 给角色批量分配知识库 */
const rolePermDialog = ref({ visible: false, role: null, kbs: [] })
const kbsOfRole = ref([])
const roleGrantMap = ref({})

async function openRolePermission(role) {
  rolePermDialog.value = { visible: true, role, kbs: [] }
  kbsOfRole.value = []
  roleGrantMap.value = {}
  // 简化为：从所有用户 KB 中收集（管理员视角所有 KB），再加载当前角色已授权的 KB
  try {
    const allUsersData = await listUsers()
    const seen = new Set()
    const candidates = []
    for (const user of allUsersData) {
      // 拉取用户的可访问 KB（接口不支持，我们直接通过 user-list 提示用户去 KbManageView 设置）
    }
    // 简化版：从 /api/kb/ 拉取当前 admin 的可访问列表（包含所有用户 KB）
    const { listKnowledgeBases } = await import('@/api/kb')
    const kbs = await listKnowledgeBases('')
    rolePermDialog.value.kbs = Array.isArray(kbs) ? kbs : []
    // 初始：全部未授权（管理员可勾选）
    for (const kb of kbs) {
      roleGrantMap.value[kb.id] = { can_read: true, can_write: false }
    }
  } catch (error) {
    ElMessage.error(error?.message || '加载失败')
  }
}

async function saveRolePermission() {
  if (!rolePermDialog.value.role) return
  const grants = Object.entries(roleGrantMap.value).map(([kid, v]) => ({
    kb_id: Number(kid),
    can_read: !!v.can_read,
    can_write: !!v.can_write
  }))
  try {
    await assignRoleKbs(rolePermDialog.value.role.id, grants)
    ElMessage.success('角色授权已更新')
    rolePermDialog.value.visible = false
    await loadRoles()
  } catch (error) {
    ElMessage.error(error?.message || '保存失败')
  }
}

/* ---------- 用户 ---------- */
const userDialogVisible = ref(false)
const userEditingId = ref(null)
const userSelectedRoleIds = ref([])

async function loadUsers() {
  loading.value = true
  try {
    const data = await listUsers()
    users.value = Array.isArray(data) ? data : []
  } catch (error) {
    ElMessage.error(error?.message || '用户列表加载失败')
  } finally {
    loading.value = false
  }
}

const roleIdToCode = computed(() => {
  const map = {}
  roles.value.forEach((r) => (map[r.id] = r.code))
  return map
})

function openUserRoles(user) {
  userEditingId.value = user.id
  // 由 role_codes 反查 role_id
  userSelectedRoleIds.value = roles.value
    .filter((r) => user.roles?.includes(r.code))
    .map((r) => r.id)
  userDialogVisible.value = true
}

async function saveUserRoles() {
  if (!userEditingId.value) return
  try {
    await assignUserRoles(userEditingId.value, userSelectedRoleIds.value)
    ElMessage.success('用户角色已更新')
    userDialogVisible.value = false
    await loadUsers()
  } catch (error) {
    ElMessage.error(error?.message || '保存失败')
  }
}

const userDialogTitle = computed(() => {
  if (!userEditingId.value) return ''
  const user = users.value.find((u) => u.id === userEditingId.value)
  return user ? `为「${user.username}」分配角色` : '分配角色'
})

onMounted(async () => {
  if (!auth.isAdmin) {
    ElMessage.error('仅管理员可访问该页面')
    router.replace('/')
    return
  }
  await Promise.all([loadRoles(), loadUsers()])
})
</script>

<template>
  <div class="page-container page-enter">
    <div class="page-head">
      <div>
        <h1 class="page-title">系统管理</h1>
        <p class="page-subtitle">仅管理员可访问，用于管理角色与用户授权</p>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="角色管理" name="roles">
        <div class="tab-toolbar">
          <el-button type="primary" class="btn-gradient" @click="openCreateRole">＋ 新建角色</el-button>
        </div>
        <el-table v-loading="loading" :data="roles" border>
          <el-table-column prop="code" label="代码" min-width="120" />
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column prop="description" label="说明" min-width="200" show-overflow-tooltip />
          <el-table-column label="用户数" width="90" align="center">
            <template #default="{ row }">{{ row.user_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="授权知识库" width="110" align="center">
            <template #default="{ row }">{{ row.kb_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="类型" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_system" size="small" effect="plain">内置</el-tag>
              <el-tag v-else size="small" type="success" effect="plain">自定义</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="220" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEditRole(row)">编辑</el-button>
              <el-button link type="primary" size="small" @click="openRolePermission(row)">知识库授权</el-button>
              <el-button link type="danger" size="small" :disabled="row.is_system" @click="removeRole(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="用户管理" name="users">
        <el-table v-loading="loading" :data="users" border>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="username" label="账号" min-width="140" />
          <el-table-column label="角色" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="code in row.roles || []" :key="code" size="small" effect="plain" class="user-role-tag">
                {{ code }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="管理员" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_admin" type="warning" size="small" effect="dark">admin</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="知识库数" width="100" align="center">
            <template #default="{ row }">{{ row.kb_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="注册时间" min-width="160" />
          <el-table-column label="操作" min-width="100" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openUserRoles(row)">分配角色</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 角色新建/编辑 -->
    <el-dialog
      v-model="roleDialogVisible"
      :title="roleEditingId ? '编辑角色' : '新建角色'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form ref="roleFormRef" :model="roleForm" :rules="roleRules" label-position="top">
        <el-form-item label="角色代码" prop="code">
          <el-input v-model="roleForm.code" :disabled="!!roleEditingId" placeholder="英文小写，如 sales" maxlength="32" show-word-limit />
          <p v-if="roleEditingId" class="form-hint">角色代码不可修改</p>
        </el-form-item>
        <el-form-item label="角色名称" prop="name">
          <el-input v-model="roleForm.name" placeholder="如：销售组" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="说明" prop="description">
          <el-input v-model="roleForm.description" type="textarea" :rows="3" resize="none" maxlength="255" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" @click="submitRole">{{ roleEditingId ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <!-- 角色 → 知识库授权 -->
    <el-dialog
      v-model="rolePermDialog.visible"
      :title="`分配知识库 · ${rolePermDialog.role?.name || ''}`"
      width="720px"
      :close-on-click-modal="false"
      append-to-body
    >
      <p class="form-hint">勾选后，该角色下全部用户可按对应权限访问本知识库</p>
      <el-table :data="rolePermDialog.kbs" size="small" border max-height="420">
        <el-table-column prop="name" label="知识库" min-width="160" />
        <el-table-column label="所有者" min-width="100">
          <template #default="{ row }">
            {{ row.access_type === 'owner' ? '本人' : row.owner_id || '其他' }}
          </template>
        </el-table-column>
        <el-table-column label="可读" width="80" align="center">
          <template #default="{ row }">
            <el-checkbox
              :model-value="roleGrantMap[row.id]?.can_read"
              @update:model-value="(val) => { if (!roleGrantMap[row.id]) roleGrantMap[row.id] = {}; roleGrantMap[row.id].can_read = val }"
            />
          </template>
        </el-table-column>
        <el-table-column label="可写" width="80" align="center">
          <template #default="{ row }">
            <el-checkbox
              :model-value="roleGrantMap[row.id]?.can_write"
              @update:model-value="(val) => { if (!roleGrantMap[row.id]) roleGrantMap[row.id] = {}; roleGrantMap[row.id].can_write = val }"
            />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="rolePermDialog.visible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveRolePermission">保存</el-button>
      </template>
    </el-dialog>

    <!-- 用户角色分配 -->
    <el-dialog
      v-model="userDialogVisible"
      :title="userDialogTitle"
      width="480px"
      :close-on-click-modal="false"
    >
      <p class="form-hint">至少保留一个角色（admin 也可被剥离）</p>
      <el-checkbox-group v-model="userSelectedRoleIds">
        <el-checkbox v-for="r in roles" :key="r.id" :value="r.id" :label="r.id" class="user-role-check">
          <span class="user-role-check-text">
            <b>{{ r.name }}</b>
            <span class="user-role-check-code">{{ r.code }}</span>
          </span>
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveUserRoles">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tab-toolbar {
  margin-bottom: 12px;
  display: flex;
  justify-content: flex-end;
}
.user-role-tag {
  margin-right: 4px;
  margin-bottom: 4px;
}
.form-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--text-muted);
}
.user-role-check {
  display: flex;
  width: 100%;
  margin: 6px 0;
}
.user-role-check-text {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.user-role-check-code {
  font-size: 11.5px;
  color: var(--text-muted);
}
</style>
