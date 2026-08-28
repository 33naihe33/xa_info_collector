// web/frontend/vite.config.ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    // PWA 暂时禁用：Service Worker 拦截导出请求导致 Word 文件无法下载
    // 如需 PWA 功能，需要精确配置排除 /api/reports/*/export 路径
    // VitePWA({
    //   registerType: 'autoUpdate',
    //   manifest: { ... },
    // }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
