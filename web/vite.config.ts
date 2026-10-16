/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API spine lives on :8710 (Python truth layer). The SPA only proxies; it never re-implements scoring.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, fs: { allow: [".."] }, proxy: { "/api": { target: "http://127.0.0.1:8710", rewrite: (p) => p.replace(/^\/api/, "") } } },
  test: { environment: "jsdom", globals: true, env: { VITE_API_BASE: "http://api.test" }, exclude: ["**/node_modules/**", "**/dist/**", "**/e2e/**"] },
});
