import { afterEach, describe, expect, it, vi } from "vitest";

// #148: every req() started inside withAbortSignal carries that signal, and an abort is
// surfaced as an AbortError (not as "Unable to reach API").
describe("api requests and the ambient abort signal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("passes the ambient signal to fetch for each call started inside withAbortSignal", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal("fetch", fetchSpy);
    // Both imported fresh: vi.resetModules() gives api.ts a new abortScope instance.
    const { api } = await import("../lib/api");
    const { withAbortSignal } = await import("../lib/abortScope");
    const controller = new AbortController();

    await withAbortSignal(controller.signal, () =>
      Promise.all([api.cashDeposits("2026-02", "SGD"), api.cryptoSummary("2026-02", "SGD")]),
    );
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    for (const call of fetchSpy.mock.calls) {
      expect((call[1] as RequestInit).signal).toBe(controller.signal);
    }

    // Outside the scope, no signal.
    await api.health();
    expect((fetchSpy.mock.calls[2][1] as RequestInit).signal).toBeUndefined();
  });

  it("rethrows an abort as AbortError instead of a network error", async () => {
    const fetchSpy = vi.fn((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
    });
    vi.stubGlobal("fetch", fetchSpy);
    // Both imported fresh: vi.resetModules() gives api.ts a new abortScope instance.
    const { api } = await import("../lib/api");
    const { withAbortSignal } = await import("../lib/abortScope");
    const controller = new AbortController();

    const pending = withAbortSignal(controller.signal, () => api.cashDeposits("2026-02", "SGD"));
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
