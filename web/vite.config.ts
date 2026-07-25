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
  },
});
