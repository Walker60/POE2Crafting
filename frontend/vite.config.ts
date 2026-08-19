import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-mode only: proxies API calls to `poe2craft serve`'s FastAPI backend
    // (default http://127.0.0.1:8000) so the SPA can call same-origin `/api/...`
    // paths without needing any CORS configuration on the backend.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
