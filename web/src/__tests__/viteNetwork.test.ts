import { describe, expect, it } from "vitest";
import { isTrustedAddress } from "../../vite.network";
import { buildRealtimeUrl } from "../lib/realtime";

describe("isTrustedAddress", () => {
  it.each([
    "127.0.0.1",
    "::1",
    "::ffff:127.0.0.1",
    "100.64.0.1",
    "100.100.100.100",
    "::ffff:100.64.10.20",
    "100.127.255.255",
    "fd7a:115c:a1e0::1234",
  ])("trusts %s", (addr) => {
    expect(isTrustedAddress(addr)).toBe(true);
  });

  it.each([
    "192.168.50.74",
    "::ffff:192.168.1.20",
    "10.0.0.5",
    "172.16.0.9",
    "100.63.255.255",
    "100.128.0.1",
    "8.8.8.8",
    "fe80::1",
    "fd7b:115c:a1e0::1",
    "",
    undefined,
    null,
  ])("rejects %s", (addr) => {
    expect(isTrustedAddress(addr)).toBe(false);
  });
});

describe("buildRealtimeUrl", () => {
  it("resolves a relative proxy base against the page and picks ws/wss", () => {
    expect(buildRealtimeUrl("/api", "http://100.100.100.100:5173/stocks").toString()).toBe(
      "ws://100.100.100.100:5173/api/realtime/ws",
    );
    expect(buildRealtimeUrl("/api", "https://app.example.com/").toString()).toBe(
      "wss://app.example.com/api/realtime/ws",
    );
  });

  it("keeps absolute bases working", () => {
    expect(buildRealtimeUrl("http://localhost:8001", "http://localhost:5173/").toString()).toBe(
      "ws://localhost:8001/realtime/ws",
    );
    expect(buildRealtimeUrl("https://api.example.com", "https://app.example.com/").toString()).toBe(
      "wss://api.example.com/realtime/ws",
    );
  });
});
