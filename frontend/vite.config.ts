import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-antd': ['antd', '@ant-design/icons'],
          'vendor-charts': ['echarts', 'echarts-for-react'],
          'vendor-markdown': ['@toast-ui/editor', '@uiw/react-md-editor', 'react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'rehype-highlight', 'katex'],
          'vendor-offline': ['dexie', 'dexie-react-hooks', 'zustand'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
