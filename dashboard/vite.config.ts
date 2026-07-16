// Vite config (PRD §6). Build output goes straight to sanjaya/server/static so
// FastAPI serves the SPA at / with zero copy steps. Dev server proxies /api to
// the running sanjayad so `npm run dev` works against real data.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../sanjaya/server/static",
    emptyOutDir: true,
    reportCompressedSize: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8756",
    },
  },
});
