import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 统一启动时使用实际后端地址；单独启动时仍默认连接 8000。
const apiTarget = process.env.AGENT_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/chat': apiTarget,
      '/health': apiTarget,
    },
  },
})