import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  build: {
    // The deployment Mac runs Monterey's WKWebView (Safari 15+).
    target: "safari15",
    cssTarget: "safari15",
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
      "/api": "http://127.0.0.1:8765",
      "/auth": "http://127.0.0.1:8765",
    },
  },
});
