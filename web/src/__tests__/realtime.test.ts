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
  function refreshResponse(token: string | null) {
    if (!token) {
      return { ok: false, status: 401, json: () => Promise.resolve({ detail: "invalid" }), text: () => Promise.resolve("{}") };
    }
    const body = { access_token: token, token_type: "bearer", expires_in: 3600 };
    return { ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) };
  }

  it("refreshes the login and reconnects when the server closes with 4401 (#364)", async () => {
    vi.useFakeTimers();
    const renewed = makeToken(3600);
    const fetchSpy = vi.fn().mockResolvedValue(refreshResponse(renewed));
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const { setAccessToken } = await import("../lib/api");
    setAccessToken(makeToken(3600));
    const { subscribeToRealtimeTopic, REALTIME_CLOSE_SIGN_IN_AGAIN } = await import("../lib/realtime");
    const unsubscribe = subscribeToRealtimeTopic("portfolio-refresh", {});
    await vi.advanceTimersByTimeAsync(0);
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(fetchSpy).not.toHaveBeenCalled();

    MockWebSocket.instances[0].emit("open");
    MockWebSocket.instances[0].emit("close", { code: REALTIME_CLOSE_SIGN_IN_AGAIN });
    await vi.advanceTimersByTimeAsync(1100);

    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining("/auth/refresh"), expect.any(Object));
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).toContain(encodeURIComponent(renewed));

    unsubscribe();
    vi.useRealTimers();
  });

  it("stops reconnecting when the session has ended (refresh refused after 4401)", async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.fn().mockResolvedValue(refreshResponse(null));
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const { setAccessToken } = await import("../lib/api");
    setAccessToken(makeToken(3600));
    const { subscribeToRealtimeTopic, REALTIME_CLOSE_SIGN_IN_AGAIN } = await import("../lib/realtime");
    const statuses: string[] = [];
    const unsubscribe = subscribeToRealtimeTopic("portfolio-refresh", { onStatusChange: (s) => statuses.push(s) });
    await vi.advanceTimersByTimeAsync(0);

    MockWebSocket.instances[0].emit("open");
    MockWebSocket.instances[0].emit("close", { code: REALTIME_CLOSE_SIGN_IN_AGAIN });
    await vi.advanceTimersByTimeAsync(5000);

    expect(fetchSpy).toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(statuses[statuses.length - 1]).toBe("disconnected");

    unsubscribe();
    vi.useRealTimers();
  });
});
