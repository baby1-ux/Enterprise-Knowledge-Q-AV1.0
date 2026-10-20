<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

// 顶部导航 + 主内容区
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const navItems = [
  { label: '对话', path: '/chat', match: ['/chat'] },
  { label: '知识库', path: '/kb', match: ['/kb'] }
]

// 用户名首字符作为头像
const avatarText = computed(() => (auth.username || '用').slice(0, 1).toUpperCase())

/** 判断导航高亮（知识库下的文档/分块页同样高亮「知识库」） */
function isActive(item) {
  return item.match.some((prefix) => route.path === prefix || route.path.startsWith(`${prefix}/`))
}

/** 下拉菜单命令 */
async function handleCommand(command) {
  if (command !== 'logout') return
  auth.logout()
  ElMessage.success('已退出登录')
  await router.replace('/login')
}

onMounted(async () => {
  // 刷新页面后若本地缺少用户信息，则回源拉取一次
  if (auth.isLoggedIn && !auth.user) {
    try {
      await auth.loadCurrentUser()
    } catch {
      // 401 已由请求层统一处理（清登录态并跳转登录页）
    }
  }
})
</script>

<template>
  <div class="main-layout">
    <header class="app-header">
      <div class="header-inner">
        <router-link class="brand" to="/chat">
          <span class="brand-mark">知</span>
          <span class="brand-text">
            <strong>企业知识问答</strong>
            <em>知识库 · 检索 · 生成</em>
          </span>
        </router-link>

        <nav class="app-nav">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ 'is-active': isActive(item) }"
          >
            {{ item.label }}
          </router-link>
        </nav>

        <div class="header-right">
          <div class="user-chip">
            <span class="user-avatar">{{ avatarText }}</span>
            <span class="user-name ellipsis">{{ auth.username }}</span>
            <el-dropdown trigger="click" placement="bottom-end" @command="handleCommand">
              <span class="user-caret" title="账号操作">▾</span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="logout">退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </div>
    </header>

    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade-slide" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.main-layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  min-height: 100dvh;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(18px);
  background: rgba(255, 255, 255, 0.78);
  border-bottom: 1px solid var(--border-color);
}

.header-inner {
  display: flex;
  align-items: center;
  gap: 28px;
  height: var(--header-height);
  max-width: var(--content-max);
  margin: 0 auto;
  padding: 0 28px;
}

/* 品牌 */
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 12px;
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  background: var(--brand-gradient);
  background-size: 160% 160%;
  box-shadow: var(--shadow-brand);
  animation: gradientFlow 6s ease infinite;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}

.brand-text strong {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
  letter-spacing: 0.2px;
}

.brand-text em {
  font-style: normal;
  font-size: 11px;
  color: var(--text-muted);
  letter-spacing: 0.6px;
}

/* 导航 */
.app-nav {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.06);
}

.nav-item {
  position: relative;
  padding: 7px 20px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-sub);
  border-radius: 999px;
  transition: all var(--transition-base);
}

.nav-item:hover {
  color: var(--brand-1);
  background: rgba(255, 255, 255, 0.75);
}

.nav-item.is-active {
  color: #fff;
  background: var(--brand-gradient);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}

/* 右侧用户区 */
.header-right {
  margin-left: auto;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 5px;
  border-radius: 999px;
  background: #fff;
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--transition-base), transform var(--transition-base);
}

.user-chip:hover {
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.user-avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: var(--brand-gradient);
}

.user-name {
  max-width: 120px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-sub);
}

.user-caret {
  cursor: pointer;
  font-size: 11px;
  color: var(--text-muted);
  outline: none;
  transition: color var(--transition-fast);
}

.user-caret:hover {
  color: var(--brand-1);
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

@media (max-width: 1023px) {
  .header-inner {
    gap: 14px;
    padding: 0 16px;
  }

  .brand-text em {
    display: none;
  }

  .nav-item {
    padding: 6px 14px;
    font-size: 13px;
  }

  .user-name {
    display: none;
  }
}
</style>
