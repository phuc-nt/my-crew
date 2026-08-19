/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// M4: the SPA is served BY FastAPI as committed static under /static/app/ (zero extra
// runtime process). `base` aligns with that mount; `build.outDir` writes the committed dist.
// Dev: `vite dev` proxies /api to the FastAPI server on 127.0.0.1:8765.
export default defineConfig({
  plugins: [react()],
  // S5: the SPA is served at `/` (StaticFiles html=True). Assets resolve under `/assets`.
  base: '/',
  build: {
    outDir: '../my_crew/server/static/app',
    emptyOutDir: true,
    // The one chunk above the default 500 kB warning is the 3D office (~900 kB, of which
    // ~2 MB of source is three + @react-three/fiber). It is already behind React.lazy, so
    // it only downloads for someone who opens /office — splitting it further would just
    // fragment one view's own dependency. The limit sits just above it so the warning
    // still fires for anything NEW that grows past that bar.
    chunkSizeWarningLimit: 950,
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
    // Playwright specs live in e2e/ and must never run under vitest — @playwright/test
    // throws on foreign runners and fails the suite at collect time.
    exclude: ['**/node_modules/**', 'e2e/**', 'e2e-cold-start/**'],
  },
})
