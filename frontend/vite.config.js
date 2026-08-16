import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物输出到项目根目录的 dist/，由 webapp.py 直接伺服
export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
})
