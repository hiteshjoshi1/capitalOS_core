import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { trustedNetworkOnly } from "./vite.network";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  // Where the dev server forwards `/api/*`. Set VITE_API_BASE=/api (web/.env.local)
  // to have the browser talk only to this server, so the API port never has to be
  // reachable from other devices.
  const apiTarget = `http://127.0.0.1:${env.VITE_API_PORT || "8000"}`;

  return {
    plugins: [
      react(),
      // Set VITE_ALLOW_LAN=1 to serve the whole local network, not just localhost + tailnet.
      trustedNetworkOnly({ enabled: env.VITE_ALLOW_LAN !== "1" }),
    ],
    server: {
      // Vite's default host resolves to IPv6 (::1) first on some systems,
      // which breaks reaching the dev server from other devices (e.g. over
      // Tailscale). Bind to all interfaces/both stacks instead; the
      // trustedNetworkOnly plugin above restricts who may actually connect.
      host: true,
      // Vite 7 rejects requests whose Host header isn't localhost or a bare IP
      // (DNS-rebinding protection). Tailscale MagicDNS names
      // (<machine>.<tailnet>.ts.net) would get a 403, so allow that suffix only.
      // Do NOT set this to `true` — it disables the check for every hostname.
      allowedHosts: [".ts.net"],
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
