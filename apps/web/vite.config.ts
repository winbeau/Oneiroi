import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type ProxyOptions } from "vite";

const apiProxyTarget = process.env.ONEIROI_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const apiProxyUser = process.env.ONEIROI_API_PROXY_USER?.trim();
const apiProxy: ProxyOptions = {
  target: apiProxyTarget,
  changeOrigin: true,
  configure(proxy) {
    if (!apiProxyUser) return;
    proxy.on("proxyReq", (proxyRequest) => {
      proxyRequest.setHeader(
        "Cookie",
        `oneiroi_user=${encodeURIComponent(apiProxyUser)}`,
      );
    });
  },
};
const proxy = {
  "/v1": apiProxy,
  "/healthz": apiProxy,
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    proxy,
  },
});
