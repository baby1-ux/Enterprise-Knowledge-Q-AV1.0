<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchCaptcha } from '@/api/auth'

/**
 * 图形验证码输入组件
 * - 输入框 + 图片，点击图片刷新
 * - 通过 v-model:code / v-model:captcha-id 双向绑定
 */
const props = defineProps({
  code: { type: String, default: '' },
  captchaId: { type: String, default: '' }
})
const emit = defineEmits(['update:code', 'update:captchaId'])

const image = ref('')
const loading = ref(false)

/** 获取（刷新）验证码图片 */
async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const data = await fetchCaptcha()
    image.value = data?.image || ''
    emit('update:captchaId', data?.captcha_id || '')
    emit('update:code', '')
  } catch (error) {
    image.value = ''
    ElMessage.error(error?.message || '验证码加载失败，请点击重试')
  } finally {
    loading.value = false
  }
}

/** 输入处理：限制 4 位、去除空格 */
function handleInput(value) {
  emit('update:code', String(value || '').replace(/\s/g, '').slice(0, 4))
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<template>
  <div class="captcha-row">
    <el-input
      :model-value="code"
      maxlength="4"
      size="large"
      placeholder="请输入验证码"
      class="captcha-input"
      @input="handleInput"
    />
    <button type="button" class="captcha-image-btn" :disabled="loading" title="点击刷新验证码" @click="refresh">
      <img v-if="image" :src="image" alt="图形验证码" class="captcha-image" />
      <span v-else class="captcha-fallback">{{ loading ? '加载中…' : '点击获取' }}</span>
      <span class="captcha-mask">点击刷新</span>
    </button>
  </div>
</template>

<style scoped>
.captcha-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.captcha-input {
  flex: 1;
  min-width: 0;
}

.captcha-image-btn {
  position: relative;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 128px;
  height: 40px;
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  background: linear-gradient(135deg, #f7f6ff 0%, #efeefe 100%);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  transition: all var(--transition-fast);
}

.captcha-image-btn:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.16);
}

.captcha-image-btn:disabled {
  cursor: wait;
  opacity: 0.75;
}

.captcha-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.captcha-fallback {
  font-size: 12px;
  color: var(--text-muted);
}

.captcha-mask {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 11px;
  color: #fff;
  background: rgba(99, 102, 241, 0.72);
  opacity: 0;
  transition: opacity var(--transition-base);
}

.captcha-image-btn:hover .captcha-mask {
  opacity: 1;
}

@media (max-width: 480px) {
  .captcha-image-btn {
    width: 104px;
  }
}
</style>
