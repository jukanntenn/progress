/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/src/i18n/')) {
            return 'index'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/healthz': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/readyz': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    // e2e/ is a separate Playwright suite (its own pnpm workspace + deps).
    // Excluding it here keeps vitest scoped to src/ unit/component tests and
    // avoids importing @playwright/test, which breaks under jsdom.
    exclude: ['node_modules', 'e2e'],
    // Coverage is on by default for any `pnpm test` run (mirrors the backend's
    // `addopts = "--cov=progress ..."` in pyproject.toml). Reports: text to the
    // terminal, xml for codecov (CI), html for local browsing, json for
    // tooling. provider is pinned to v8 and matched to vitest's version in
    // devDependencies.
    coverage: {
      provider: 'v8',
      // clover → clover.xml for codecov (the JS-native XML format codecov
      // recognizes; istanbul-reports has no plain 'xml' reporter).
      reporter: ['text', 'json', 'html', 'clover'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/main.tsx', 'src/api/schema.ts', 'src/test/**'],
    },
  },
})
