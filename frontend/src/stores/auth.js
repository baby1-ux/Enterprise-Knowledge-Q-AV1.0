import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchCurrentUser, login as loginApi, register as registerApi } from '@/api/auth'
import { clearAuth, getStoredUser, getToken, setAuth } from '@/api/request'

/**
 * 登录态 Store：token + 当前用户信息
 * token 与用户信息同时持久化到 localStorage，刷新页面后仍保持登录
 */
export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const user = ref(getStoredUser())
  const loading = ref(false)

  const isLoggedIn = computed(() => Boolean(token.value))
  const username = computed(() => user.value?.username || '用户')

  /** 登录：成功后写入 token 与用户信息 */
  async function login(payload) {
    loading.value = true
    try {
      const data = await loginApi(payload)
      token.value = data?.access_token || ''
      user.value = data?.user || null
      setAuth(token.value, user.value)
      return data
    } finally {
      loading.value = false
    }
  }

  /** 注册：不做登录态处理，由页面在成功后跳转登录页 */
  async function register(payload) {
    loading.value = true
    try {
      return await registerApi(payload)
    } finally {
      loading.value = false
    }
  }

  /** 拉取当前用户（刷新页面后校验 token 是否仍有效） */
  async function loadCurrentUser() {
    if (!token.value) return null
    const data = await fetchCurrentUser()
    user.value = data || null
    setAuth(token.value, user.value)
    return user.value
  }

  /** 退出登录：清除本地登录态 */
  function logout() {
    token.value = ''
    user.value = null
    clearAuth()
  }

  return { token, user, loading, isLoggedIn, username, login, register, loadCurrentUser, logout }
})
