import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The backend (FastAPI) serves the built app in production. In development, Vite serves
// the app and forwards /api to the backend started with `make dev-backend`.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true }, // ws: the server feed
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
