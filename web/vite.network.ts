import type { Plugin } from "vite";

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

/**
 * True for this machine (127.0.0.0/8, ::1) and for Tailscale
 * (100.64.0.0/10, fd7a:115c:a1e0::/48). IPv4 clients of a dual-stack socket
 * show up as "::ffff:a.b.c.d".
 */
export function isTrustedAddress(raw: string | null | undefined): boolean {
  if (!raw) return false;
  const addr = raw.toLowerCase().replace(/^::ffff:/, "");
  const v4 = IPV4.exec(addr);
  if (v4) {
    const first = Number(v4[1]);
    const second = Number(v4[2]);
    return first === 127 || (first === 100 && second >= 64 && second <= 127);
  }
  return addr === "::1" || addr.startsWith("fd7a:115c:a1e0:");
}

/**
 * The dev/preview server listens on every interface (`host: true`) so a phone
 * on the tailnet can reach it, but it should not serve anyone else on the
 * local network. This drops any TCP connection from outside localhost and the
 * tailnet before a single byte of HTTP or WebSocket traffic is handled.
 */
export function trustedNetworkOnly(options: { enabled?: boolean } = {}): Plugin {
  const { enabled = true } = options;
  return {
    name: "capitalos-trusted-network-only",
    configureServer(server) {
      if (!enabled) return;
      server.httpServer?.on("connection", (socket) => {
        if (!isTrustedAddress(socket.remoteAddress)) socket.destroy();
      });
    },
    configurePreviewServer(server) {
      if (!enabled) return;
      server.httpServer.on("connection", (socket) => {
        if (!isTrustedAddress(socket.remoteAddress)) socket.destroy();
      });
    },
  };
}
