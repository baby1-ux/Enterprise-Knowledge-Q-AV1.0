<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getKbPermission, listRoles, listUsers, updateKbPermission } from '@/api/permission'

const props = defineProps({
  kb: { type: Object, required: true }
})
const emit = defineEmits(['close', 'saved'])

const loading = ref(false)
const saving = ref(false)
const visibility = ref('private')
const roles = ref([])
const users = ref([])
const permissionData = ref({ roles: [], members: [] })

/** 把"已授权"整理成 { role_id: {can_read, can_write} } 方便 O(1) 查找 */
const roleGrantMap = ref({})
const memberGrantMap = ref({})

const visibilityOptions = [
  { value: 'private', label: '私有：仅所有者可访问' },
  { value: 'role', label: '角色共享：被授权角色可读' },
  { value: 'all', label: '全员只读：登录即可检索' }
]

/** 真实可用的角色列表（剔除 owner 自身在 user 列表中的干扰；这里都展示） */
const roleList = computed(() => roles.value.filter((r) => r.code !== 'admin' || true))

/** 用户下拉候选：所有用户，便于直授 */
const userOptions = computed(() => users.value.map((u) => ({ value: u.id, label: u.username })))

function ensureRolePerm(roleId) {
  if (!roleGrantMap.value[roleId]) roleGrantMap.value[roleId] = { can_read: true, can_write: false }
}
function ensureMemberPerm(userId) {
  if (!memberGrantMap.value[userId]) memberGrantMap.value[userId] = { can_read: true, can_write: false }
}

function syncFromPermission() {
  roleGrantMap.value = {}
  memberGrantMap.value = {}
  for (const item of permissionData.value.roles || []) {
    roleGrantMap.value[item.role_id] = { can_read: !!item.can_read, can_write: !!item.can_write }
  }
  for (const item of permissionData.value.members || []) {
    memberGrantMap.value[item.user_id] = { can_read: !!item.can_read, can_write: !!item.can_write }
  }
}

async function loadData() {
  loading.value = true
  try {
    const [permData, roleData, userData] = await Promise.all([
      getKbPermission(props.kb.id),
      listRoles(),
      listUsers()
    ])
    permissionData.value = {
      roles: Array.isArray(permData?.roles) ? permData.roles : [],
      members: Array.isArray(permData?.members) ? permData.members : []
    }
    visibility.value = permData?.visibility || 'private'
    roles.value = Array.isArray(roleData) ? roleData : []
    users.value = Array.isArray(userData) ? userData : []
    syncFromPermission()
  } catch (error) {
    ElMessage.error(error?.message || '加载授权信息失败')
  } finally {
    loading.value = false
  }
}

function setRolePermission(roleId, field, value) {
  ensureRolePerm(roleId)
  roleGrantMap.value[roleId][field] = value
}

function setMemberPermission(userId, field, value) {
  ensureMemberPerm(userId)
  memberGrantMap.value[userId][field] = value
}

function removeRoleGrant(roleId) {
  delete roleGrantMap.value[roleId]
}
function removeMemberGrant(userId) {
  delete memberGrantMap.value[userId]
}

function addRoleGrant(roleId) {
  if (!roleId) return
  ensureRolePerm(roleId)
}

function addMemberGrant(userId) {
  if (!userId) return
  ensureMemberPerm(userId)
}

const roleGrantsPayload = computed(() =>
  Object.entries(roleGrantMap.value).map(([rid, val]) => ({
    role_id: Number(rid),
    can_read: !!val.can_read,
    can_write: !!val.can_write
  }))
)
const memberGrantsPayload = computed(() =>
  Object.entries(memberGrantMap.value).map(([uid, val]) => ({
    user_id: Number(uid),
    can_read: !!val.can_read,
    can_write: !!val.can_write
  }))
)

/** 角色名/id 字典 */
const roleNameMap = computed(() => {
  const map = {}
  roles.value.forEach((r) => (map[r.id] = `${r.name}（${r.code}）`))
  return map
})

const newRoleId = ref(null)
const newMemberId = ref(null)

async function handleSave() {
  saving.value = true
  try {
    await updateKbPermission(props.kb.id, roleGrantsPayload.value, memberGrantsPayload.value)
    ElMessage.success('授权已更新')
    emit('saved')
  } catch (error) {
    ElMessage.error(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(() => props.kb, (val) => {
  if (val) loadData()
}, { immediate: true })

onMounted(loadData)
</script>

<template>
  <el-dialog
    :model-value="true"
    :title="`知识库授权 · ${kb.name}`"
    width="640px"
    :close-on-click-modal="false"
    append-to-body
    @update:model-value="emit('close')"
  >
    <div v-loading="loading">
      <section class="perm-section">
        <h4 class="perm-section-title">可见范围</h4>
        <el-radio-group v-model="visibility" disabled>
          <el-radio-button v-for="item in visibilityOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-radio-group>
        <p class="perm-hint">可见范围由所有者编辑（当前仅展示）</p>
      </section>

      <section class="perm-section">
        <h4 class="perm-section-title">角色授权</h4>
        <p class="perm-hint">勾选后，该角色下全部用户可按对应权限访问本知识库</p>

        <el-table :data="roleGrantsPayload" size="small" border empty-text="暂未给任何角色授权">
          <el-table-column label="角色" min-width="160">
            <template #default="{ row }">{{ roleNameMap[row.role_id] || `角色 #${row.role_id}` }}</template>
          </el-table-column>
          <el-table-column label="可读" width="80" align="center">
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.can_read"
                @update:model-value="(val) => setRolePermission(row.role_id, 'can_read', val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="可写" width="80" align="center">
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.can_write"
                @update:model-value="(val) => setRolePermission(row.role_id, 'can_write', val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="removeRoleGrant(row.role_id)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="perm-add-row">
          <el-select v-model="newRoleId" placeholder="选择要授权的角色" size="small" style="width: 280px" clearable @change="addRoleGrant">
            <el-option v-for="r in roleList" :key="r.id" :value="r.id" :label="`${r.name}（${r.code}）`" />
          </el-select>
          <span class="perm-add-hint">从下拉中选择角色，自动加入列表</span>
        </div>
      </section>

      <section class="perm-section">
        <h4 class="perm-section-title">人员直授</h4>
        <p class="perm-hint">直接指定个别用户（解决「只给某一个人」的零散需求）</p>

        <el-table :data="memberGrantsPayload" size="small" border empty-text="暂未直授任何用户">
          <el-table-column label="用户" min-width="160">
            <template #default="{ row }">
              {{ userOptions.find((u) => u.value === row.user_id)?.label || `用户 #${row.user_id}` }}
            </template>
          </el-table-column>
          <el-table-column label="可读" width="80" align="center">
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.can_read"
                @update:model-value="(val) => setMemberPermission(row.user_id, 'can_read', val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="可写" width="80" align="center">
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.can_write"
                @update:model-value="(val) => setMemberPermission(row.user_id, 'can_write', val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="removeMemberGrant(row.user_id)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="perm-add-row">
          <el-select v-model="newMemberId" placeholder="选择要直授的用户" size="small" style="width: 280px" clearable filterable @change="addMemberGrant">
            <el-option v-for="u in userOptions" :key="u.value" :value="u.value" :label="u.label" />
          </el-select>
          <span class="perm-add-hint">所有者本人天然拥有全部权限，无需授权</span>
        </div>
      </section>
    </div>

    <template #footer>
      <el-button @click="emit('close')">取消</el-button>
      <el-button type="primary" class="btn-gradient" :loading="saving" @click="handleSave">保存授权</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.perm-section {
  margin-bottom: 22px;
}
.perm-section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
}
.perm-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-muted);
}
.perm-add-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.perm-add-hint {
  font-size: 11.5px;
  color: var(--text-muted);
}
</style>
