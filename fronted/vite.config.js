//配置开发服务器，将聊天请求转发给 FastAPI
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/chat': 'http://127.0.0.1:8000',
    },
  },
})