import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: `npm run dev` proxies /api to the FastAPI server (`research api serve`, default port 8765).
// Prod: `npm run build` emits dist/, which `research api serve` mounts at /.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  build: { outDir: 'dist', sourcemap: false, cssMinify: 'esbuild' },
})
