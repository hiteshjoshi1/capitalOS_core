import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Vite's default host resolves to IPv6 (::1) first on some systems,
    // which breaks reaching the dev server from other devices (e.g. over
    // Tailscale). Bind to all interfaces/both stacks instead.
    host: true,
    // Vite 7 rejects requests whose Host header isn't localhost or a bare IP
    // (DNS-rebinding protection). Tailscale MagicDNS names
    // (<machine>.<tailnet>.ts.net) would get a 403, so allow that suffix only.
    // Do NOT set this to `true` — it disables the check for every hostname.
    allowedHosts: [".ts.net"],
  },
});
