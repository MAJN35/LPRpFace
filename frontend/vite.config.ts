import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production build is served by nginx, which proxies /api to the backend (same origin, no CORS).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: process.env.BACKEND_URL ?? "http://127.0.0.1:8000", ws: true } } },
  // 15 s per test: the Jetson runs all test files in parallel on its CPU, where UI tests take several seconds
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], testTimeout: 15000 },
});
