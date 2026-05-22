import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget = process.env.API_PROXY_TARGET || "http://localhost:8000";
const defaultAllowedHosts = [
  "extbackup.sofianechaoui.fr",
  "localhost",
  "127.0.0.1",
  "192.168.1.103",
];

const allowedHosts = (process.env.WEB_ALLOWED_HOSTS || defaultAllowedHosts.join(","))
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: Number(process.env.WEB_PORT || 5173),
    allowedHosts,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      "/health": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
});
