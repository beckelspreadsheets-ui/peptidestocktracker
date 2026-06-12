import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // dev: proxy /api to the local API so the dashboard uses relative URLs
    // (same as production, where the API serves the built dashboard).
    proxy: { "/api": "http://localhost:8000" },
  },
});
