import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production build is served by nginx, which proxies /api to the backend (same origin, no CORS).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: process.env.BACKEND_URL ?? "http://127.0.0.1:8000", ws: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
