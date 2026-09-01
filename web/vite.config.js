import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API is uvicorn on 8000, the dev server is Vite on 5173. Proxying /api keeps
// the browser on one origin, so nothing here depends on the CORS middleware being
// permissive — that is there for the demo room, not for this.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
})
