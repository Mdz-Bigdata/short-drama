import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const DEFAULT_DEV_PORT = 5173
// FRONTEND_PORT is shared with the backend, which derives its default CORS
// origins from it, so the two stay in step when the port is moved.
const devPort = Number(process.env.FRONTEND_PORT) || DEFAULT_DEV_PORT

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { port: devPort },
  test: {
    // Request assertions name the default backend address. Pin it so a
    // developer's own .env.local cannot change what the suite expects.
    env: { VITE_API_BASE_URL: 'http://localhost:8000' },
  },
})
