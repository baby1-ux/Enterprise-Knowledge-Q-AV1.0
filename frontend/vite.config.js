import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 配置：开发环境把 /api 代理到 FastAPI 后端，避免浏览器跨域
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    open: false,
    proxy: {
      // 后端接口前缀本身就是 /api，因此代理不做路径重写
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1600
  }
})
