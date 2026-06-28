/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// M4: the SPA is served BY FastAPI as committed static under /static/app/ (zero extra
// runtime process). `base` aligns with that mount; `build.outDir` writes the committed dist.
// Dev: `vite dev` proxies /api to the FastAPI server on 127.0.0.1:8765.
export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  build: {
    outDir: '../src/server/static/app',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
  },
})
