<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CaptchaInput from '@/components/CaptchaInput.vue'
import { useAuthStore } from '@/stores/auth'

// 登录页：账号 + 密码 + 图形验证码
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref(null)
const captchaRef = ref(null)
const submitting = ref(false)

const form = reactive({
  username: '',
  password: '',
  captcha_code: '',
  captcha_id: ''
})

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  captcha_code: [{ required: true, message: '请输入图形验证码', trigger: 'blur' }]
}

/** 提交登录 */
async function handleSubmit() {
  if (submitting.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await auth.login({
      username: form.username.trim(),
      password: form.password,
      captcha_id: form.captcha_id,
      captcha_code: form.captcha_code.trim()
    })
    ElMessage.success('登录成功，欢迎回来')
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect ? route.query.redirect : '/chat'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error?.message || '登录失败，请稍后重试')
    // 验证码使用一次即失效，失败后立即刷新
    captchaRef.value?.refresh()
    form.captcha_code = ''
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <!-- 左侧品牌介绍区 -->
    <section class="auth-brand">
      <div class="brand-orb orb-1"></div>
      <div class="brand-orb orb-2"></div>
      <div class="brand-orb orb-3"></div>

      <div class="brand-content">
        <div class="brand-badge">RAG · 企业内容知识问答</div>
        <h1 class="brand-title">
          让知识开口说话
          <span>KNOWLEDGE THAT ANSWERS</span>
        </h1>
        <p class="brand-slogan">
          上传企业文档，系统自动解析、切块并向量化；提问时先从知识库检索依据，再由大模型生成有出处、可追溯的答案。
        </p>
        <ul class="brand-points">
          <li>多知识库联合检索，回答附带引用来源</li>
          <li>流式生成逐字返回，过程实时可见</li>
          <li>文档分块可预览、可编辑、可启停</li>
        </ul>
      </div>
    </section>

    <!-- 右侧毛玻璃表单卡片 -->
    <section class="auth-panel">
      <div class="auth-card">
        <div class="auth-card-head">
          <h2 class="auth-card-title">欢迎回来</h2>
          <p class="auth-card-sub">登录后即可与你的知识库对话</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          class="auth-form"
          label-position="top"
          @keyup.enter="handleSubmit"
          @submit.prevent
        >
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              size="large"
              placeholder="请输入账号"
              autocomplete="username"
              clearable
            />
          </el-form-item>

          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              size="large"
              placeholder="请输入密码"
              autocomplete="current-password"
              show-password
            />
          </el-form-item>

          <el-form-item prop="captcha_code">
            <CaptchaInput ref="captchaRef" v-model:code="form.captcha_code" v-model:captcha-id="form.captcha_id" />
          </el-form-item>

          <el-button type="primary" class="auth-submit btn-gradient" :loading="submitting" @click="handleSubmit">
            登 录
          </el-button>
        </el-form>

        <div class="auth-switch">
          还没有账号？
          <router-link to="/register">立即注册</router-link>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* 页面级样式集中在 styles/main.css 的「认证页」小节 */
</style>
