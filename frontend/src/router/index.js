import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '@/api/request'
import { useAuthStore } from '@/stores/auth'
import MainLayout from '@/layouts/MainLayout.vue'

/**
 * 路由表
 * - /login、/register 为匿名页
 * - /chat、/kb、/kb/:kbId/documents、/kb/documents/:docId/chunks 需要登录
 */
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { guestOnly: true, title: '登录' }
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { guestOnly: true, title: '注册' }
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/chat',
    children: [
      {
        path: 'chat',
        name: 'chat',
        component: () => import('@/views/ChatView.vue'),
        meta: { requiresAuth: true, title: '对话' }
      },
      {
        path: 'kb',
        name: 'kb',
        component: () => import('@/views/KbManageView.vue'),
        meta: { requiresAuth: true, title: '知识库' }
      },
      {
        path: 'kb/:kbId/documents',
        name: 'kb-documents',
        component: () => import('@/views/KbDocumentsView.vue'),
        meta: { requiresAuth: true, title: '文档管理' }
      },
      {
        path: 'kb/documents/:docId/chunks',
        name: 'kb-chunks',
        component: () => import('@/views/KbChunksView.vue'),
        meta: { requiresAuth: true, title: '分块预览' }
      },
      {
        path: 'admin',
        name: 'admin',
        component: () => import('@/views/AdminView.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '系统管理' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    redirect: '/chat'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

/** 全局守卫：登录态校验 + 已登录禁止访问登录/注册页 + 管理员守卫 */
router.beforeEach((to) => {
  const hasToken = Boolean(getToken())

  if (to.meta?.requiresAuth && !hasToken) {
    return { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }

  if (to.meta?.guestOnly && hasToken) {
    return { path: '/chat' }
  }

  if (to.meta?.requiresAdmin) {
    // 异步守卫：拉取一次当前用户角色（pinia 已在登录时缓存）
    const auth = useAuthStore()
    if (!auth.isAdmin) {
      return { path: '/chat' }
    }
  }

  return true
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} · 企业知识问答系统` : '企业知识问答系统'
})

export default router
