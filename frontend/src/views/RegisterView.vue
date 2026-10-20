<script setup>
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import CaptchaInput from '@/components/CaptchaInput.vue'
import { useAuthStore } from '@/stores/auth'

// 注册页：账号 + 密码 + 确认密码 + 图形验证码
const router = useRouter()
const auth = useAuthStore()

const formRef = ref(null)
const captchaRef = ref(null)
const submitting = ref(false)

const form = reactive({
  username: '',
  password: '',
  confirm_password: '',
  captcha_code: '',
  captcha_id: ''
})

/** 校验两次密码是否一致 */
function validateConfirmPassword(rule, value, callback) {
  if (!value) {
    callback(new Error('请再次输入密码'))
    return
  }
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
    return
  }
  callback()
}

const rules = {
  username: [
    { required: true, message: '请输入账号', trigger: 'blur' },
    { min: 3, max: 32, message: '账号长度需为 3 ~ 32 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '密码长度需为 6 ~ 32 个字符', trigger: 'blur' }
  ],
  confirm_password: [{ required: true, validator: validateConfirmPassword, trigger: 'blur' }],
  captcha_code: [{ required: true, message: '请输入图形验证码', trigger: 'blur' }]
}

// 密码变化时重新校验确认密码，避免误报
watch(
  () => form.password,
  () => {
    if (form.confirm_password) formRef.value?.validateField('confirm_password').catch(() => {})
  }
)

/** 提交注册 */
async function handleSubmit() {
  if (submitting.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  // 前端先校验两次密码一致
  if (form.password !== form.confirm_password) {
    ElMessage.error('两次输入的密码不一致')
    return
  }

  submitting.value = true
  try {
    await auth.register({
      username: form.username.trim(),
      password: form.password,
      confirm_password: form.confirm_password,
      captcha_id: form.captcha_id,
      captcha_code: form.captcha_code.trim()
    })
    ElMessage.success('注册成功，请使用新账号登录')
    await router.push('/login')
  } catch (error) {
    ElMessage.error(error?.message || '注册失败，请稍后重试')
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
          三步拥有自己的知识助手
          <span>UPLOAD · PARSE · ASK</span>
        </h1>
        <p class="brand-slogan">
          创建知识库、上传离线文档、配置切块与检索方式，随后即可在对话页勾选知识库开始提问，答案自动附带引用来源。
        </p>
        <ul class="brand-points">
          <li>支持 PDF / PPT / Markdown / 图片 / DOCX</li>
          <li>切块大小与重叠大小可自定义</li>
          <li>稠密检索与混合检索自由切换</li>
        </ul>
      </div>
    </section>

    <!-- 右侧毛玻璃表单卡片 -->
    <section class="auth-panel">
      <div class="auth-card">
        <div class="auth-card-head">
          <h2 class="auth-card-title">创建账号</h2>
          <p class="auth-card-sub">注册后即可创建知识库并开始对话</p>
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
            <el-input v-model="form.username" size="large" placeholder="请输入账号" autocomplete="username" clearable />
          </el-form-item>

          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              size="large"
              placeholder="请输入密码（6 ~ 32 位）"
              autocomplete="new-password"
              show-password
            />
          </el-form-item>

          <el-form-item prop="confirm_password">
            <el-input
              v-model="form.confirm_password"
              type="password"
              size="large"
              placeholder="请再次输入密码"
              autocomplete="new-password"
              show-password
            />
          </el-form-item>

          <el-form-item prop="captcha_code">
            <CaptchaInput ref="captchaRef" v-model:code="form.captcha_code" v-model:captcha-id="form.captcha_id" />
          </el-form-item>

          <el-button type="primary" class="auth-submit btn-gradient" :loading="submitting" @click="handleSubmit">
            注 册
          </el-button>
        </el-form>

        <div class="auth-switch">
          已有账号？
          <router-link to="/login">返回登录</router-link>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* 页面级样式集中在 styles/main.css 的「认证页」小节 */
</style>
