import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const vendorChunks: Record<string, string[]> = {
  'vendor-react': ['react', 'react-dom', 'react-router-dom'],
  'vendor-charts': ['echarts', 'echarts-for-react'],
  'vendor-markdown': ['@toast-ui/editor', '@uiw/react-md-editor', 'react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'rehype-highlight', 'katex'],
  'vendor-offline': ['dexie', 'dexie-react-hooks', 'zustand'],
}

const antdOverlayModules = new Set([
  'modal',
  'drawer',
  'dropdown',
  'notification',
  'message',
  'popover',
  'tooltip',
  'popconfirm',
])

const antdDataEntryModules = new Set([
  'auto-complete',
  'checkbox',
  'date-picker',
  'form',
  'input',
  'input-number',
  'radio',
  'select',
  'slider',
  'switch',
  'upload',
])

const antdDataDisplayModules = new Set([
  'alert',
  'badge',
  'calendar',
  'card',
  'collapse',
  'descriptions',
  'empty',
  'list',
  'progress',
  'spin',
  'statistic',
  'table',
  'tag',
  'timeline',
])

function isPackageImport(id: string, pkg: string) {
  const normalized = id.replace(/\\/g, '/')
  return normalized.includes(`/node_modules/${pkg}/`) || normalized.endsWith(`/node_modules/${pkg}`)
}

function getAntdChunk(id: string) {
  const normalized = id.replace(/\\/g, '/')
  if (normalized.includes('/node_modules/@ant-design/icons/')) {
    return 'vendor-antd-icons'
  }

  const marker = '/node_modules/antd/'
  const markerIndex = normalized.indexOf(marker)
  if (markerIndex === -1) {
    return undefined
  }

  const relativePath = normalized.slice(markerIndex + marker.length)
  const parts = relativePath.split('/')
  const moduleName = parts[0] === 'es' || parts[0] === 'lib' ? parts[1] : parts[0]

  if (antdOverlayModules.has(moduleName)) {
    return 'vendor-antd-overlay'
  }
  if (antdDataEntryModules.has(moduleName)) {
    return 'vendor-antd-input'
  }
  if (antdDataDisplayModules.has(moduleName)) {
    return 'vendor-antd-display'
  }

  return 'vendor-antd-core'
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const antdChunk = getAntdChunk(id)
          if (antdChunk) {
            return antdChunk
          }
          for (const [chunkName, packages] of Object.entries(vendorChunks)) {
            if (packages.some((pkg) => isPackageImport(id, pkg))) {
              return chunkName
            }
          }
          return undefined
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    port: 5173,
    proxy: {
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
