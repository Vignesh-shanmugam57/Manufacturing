import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Vite server proxies /api to FastAPI, so the React code uses relative URLs
// and needs no CORS setup. In production FastAPI serves the built files from frontend/dist.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
});
