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
          net_worth_as_of: "2026-02-06T00:00:00+00:00",
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
