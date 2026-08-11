import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API is proxied onto the dev server's own origin rather than called
// cross-origin. That keeps the refresh cookie SameSite=Strict in development
// exactly as it will be in production, instead of relying on a relaxed
// setting that only works locally.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8010', changeOrigin: false },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
