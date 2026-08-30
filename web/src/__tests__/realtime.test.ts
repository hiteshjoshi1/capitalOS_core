import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  readonly url: string;
  private listeners = new Map<string, Array<(event?: unknown) => void>>();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  addEventListener(type: string, handler: (event?: unknown) => void) {
    const existing = this.listeners.get(type) ?? [];
    existing.push(handler);
    this.listeners.set(type, existing);
  }

  send() {}

  close() {
    this.emit("close", { code: 1000 });
  }

  emit(type: string, event?: unknown) {
    for (const handler of this.listeners.get(type) ?? []) {
      handler(event);
    }
  }
}

function b64url(value: string): string {
  return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function makeToken(expOffsetSeconds: number): string {
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({
      sub: "2",
      username: "testuser",
      exp: Math.floor(Date.now() / 1000) + expOffsetSeconds,
      type: "access",
    }),
  );
  return `${header}.${payload}.sig`;
}

describe("realtime client", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("refreshes an expired access token before opening websocket", async () => {
    const refreshedToken = makeToken(3600);
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ access_token: refreshedToken, token_type: "bearer", expires_in: 3600 }),
      text: () => Promise.resolve(JSON.stringify({ access_token: refreshedToken, token_type: "bearer", expires_in: 3600 })),
    });
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const { setAccessToken } = await import("../lib/api");
    setAccessToken(makeToken(-3600));
    const { subscribeToRealtimeTopic } = await import("../lib/realtime");

    const unsubscribe = subscribeToRealtimeTopic("portfolio-refresh", {});
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/auth/refresh"),
      expect.any(Object),
    );
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain(encodeURIComponent(refreshedToken));

    unsubscribe();
  });
});
