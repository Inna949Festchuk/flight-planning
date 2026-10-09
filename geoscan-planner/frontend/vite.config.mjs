import { defineConfig } from "vite";

const apiTarget = process.env.VITE_API_PROXY || "http://localhost:8000";

export default defineConfig({
  build: {
    outDir: "dist",
    assetsDir: "assets",
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
