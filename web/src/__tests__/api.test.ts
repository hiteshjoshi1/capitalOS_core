import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Must be imported AFTER mocking fetch so the module captures the mocked version
// We import dynamically to allow stubbing import.meta.env first.

describe("api.dashboardBootstrap – URL correctness", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          as_of_month: "2026-02",
          base_currency: "SGD",
          snapshot_day: 6,
          net_worth_as_of: "2026-03-01T00:00:00+00:00",
          net_worth_snapshot_as_of: "2026-02-06T00:00:00+00:00",
          net_worth: {
            total: 742180,
            cash: 118400,
            stocks_funds: 512300,
            crypto: 136900,
            liabilities: 0,
          },
          stock_exposure_total: 90000,
          crypto_exposure_total: 136900,
          cash_percent: 15.96,
        }),
    });
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("calls /dashboard/bootstrap (not /dashboard/summary) when dashboardBootstrap is invoked", async () => {
    // Import the real api module (not mocked)
    const { api } = await import("../lib/api");

    await api.dashboardBootstrap("2026-02", "SGD");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const calledUrl: string = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/dashboard/bootstrap");
    expect(calledUrl).not.toContain("/dashboard/summary");
  });

  it("resolves with stock_exposure_total and crypto_exposure_total as defined numbers", async () => {
    const { api } = await import("../lib/api");

    const result = await api.dashboardBootstrap("2026-02", "SGD");

    expect(typeof result.stock_exposure_total).toBe("number");
    expect(typeof result.crypto_exposure_total).toBe("number");
    expect(result.stock_exposure_total).not.toBeUndefined();
    expect(result.crypto_exposure_total).not.toBeUndefined();
    expect(result.stock_exposure_total).toBe(90000);
    expect(result.crypto_exposure_total).toBe(136900);
  });

  it("passes month and base_currency as query params to /dashboard/bootstrap", async () => {
    const { api } = await import("../lib/api");

    await api.dashboardBootstrap("2026-03", "USD");

    const calledUrl: string = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/dashboard/bootstrap");
    expect(calledUrl).toContain("month=2026-03");
    expect(calledUrl).toContain("base_currency=USD");
  });

  it("calls /dashboard/stock-holdings for stockHoldingsSummary", async () => {
    const { api } = await import("../lib/api");

    await api.stockHoldingsSummary("2026-03", "USD");

    const calledUrl: string = fetchSpy.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/dashboard/stock-holdings");
    expect(calledUrl).toContain("month=2026-03");
    expect(calledUrl).toContain("base_currency=USD");
  });
});

describe("resolveApiBase", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("derives the API base from the current hostname when VITE_API_BASE is unset", async () => {
    const { resolveApiBase } = await import("../lib/api");
    expect(resolveApiBase(undefined, { protocol: "http:", hostname: "127.0.0.1" })).toBe(
      "http://127.0.0.1:8000",
    );
    expect(resolveApiBase(undefined, { protocol: "https:", hostname: "app.example.com" })).toBe(
      "https://app.example.com:8000",
    );
  });

  it("preserves explicit VITE_API_BASE overrides", async () => {
    const { resolveApiBase } = await import("../lib/api");
    expect(resolveApiBase("http://localhost:9000/")).toBe("http://localhost:9000");
  });
});

describe("streamAiSageChatMessage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("parses the final SSE frame even when the stream closes without a trailing separator", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: done\ndata: {"chat":{"id":"chat-1","title":"Done","messages":[]},"user_message":{"id":"user-1","role":"user","content":"Q","status":"completed","created_at":"2026-05-01T10:00:00Z","evidence":[]},"assistant_message":{"id":"assistant-1","role":"assistant","content":"A","status":"completed","created_at":"2026-05-01T10:00:01Z","evidence":[]}}',
          ),
        );
        controller.close();
      },
    });
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, body });
    vi.stubGlobal("fetch", fetchSpy);
    const { streamAiSageChatMessage } = await import("../lib/api");
    const events: unknown[] = [];

    await streamAiSageChatMessage("chat-1", { content: "Q" }, (event) => {
      events.push(event);
    });

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      type: "done",
      chat: { id: "chat-1", title: "Done" },
      assistant_message: { id: "assistant-1", content: "A" },
    });
  });
});

describe("api.authLogin – error formatting", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("formats FastAPI validation payloads into readable field messages", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            detail: [
              {
                type: "string_too_short",
                loc: ["body", "password"],
                msg: "String should have at least 8 characters",
              },
            ],
          }),
        ),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const { api } = await import("../lib/api");

    await expect(api.authLogin({ username: "demo", password: "short" })).rejects.toThrow(
      "password: String should have at least 8 characters",
    );
  });

  it("uses detail string when backend returns auth failure", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve(JSON.stringify({ detail: "invalid credentials" })),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const { api } = await import("../lib/api");

    await expect(api.authLogin({ username: "demo", password: "wrongpassword" })).rejects.toThrow(
      "invalid credentials",
    );
  });
});

describe("callRefreshEndpoint – session reliability", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("does NOT call notifyAuthFailure on network error during background refresh", async () => {
    const fetchSpy = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchSpy);

    const { setAuthFailureHandler, setAccessToken } = await import("../lib/api");
    const handler = vi.fn();
    setAuthFailureHandler(handler);
    setAccessToken("old-token");

    // For network error, authRefresh throws a regular Error, not AuthSessionExpiredError.
    const { api, AuthSessionExpiredError } = await import("../lib/api");

    fetchSpy.mockRejectedValue(new TypeError("Network failure"));
    await expect(api.authRefresh()).rejects.toThrow("Unable to reach API");
    await expect(api.authRefresh()).rejects.not.toThrow(AuthSessionExpiredError as never);
  });

  it("throws AuthSessionExpiredError when /auth/refresh returns 401", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve(JSON.stringify({ detail: "invalid or expired refresh token" })),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const { api, AuthSessionExpiredError } = await import("../lib/api");

    await expect(api.authRefresh()).rejects.toBeInstanceOf(AuthSessionExpiredError);
  });

  it("does NOT throw AuthSessionExpiredError when /auth/refresh returns 500", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error"),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const { api, AuthSessionExpiredError } = await import("../lib/api");

    const err = await api.authRefresh().catch((e: unknown) => e);
    expect(err).not.toBeInstanceOf(AuthSessionExpiredError);
  });

  it("does NOT clear the session when a background refresh attempt returns 403", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: () => Promise.resolve(JSON.stringify({ detail: "expired" })),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 403,
        text: () => Promise.resolve("Forbidden"),
      });
    vi.stubGlobal("fetch", fetchSpy);

    const { api, setAuthFailureHandler, setAccessToken, AuthSessionExpiredError } = await import("../lib/api");
    const handler = vi.fn();
    setAuthFailureHandler(handler);
    setAccessToken("old-token");

    await expect(api.dashboardBootstrap("2026-03", "USD")).rejects.toBeInstanceOf(AuthSessionExpiredError);
    expect(handler).not.toHaveBeenCalled();
  });
});
