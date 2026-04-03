import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
};

function okJson(body: unknown = {}): MockResponse {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  };
}

describe("api client coverage", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("exercises endpoint wrappers and multipart upload helpers", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(okJson({}));
    vi.stubGlobal("fetch", fetchSpy);
    const { api, setAccessToken, getAccessToken } = await import("../lib/api");

    setAccessToken("token-1");
    expect(getAccessToken()).toBe("token-1");

    const sampleFile = new File(["x"], "sample.csv", { type: "text/csv" });

    await api.health();
    await api.authSignup({ username: "demo", password: "Password123!", display_name: "Demo" });
    await api.authLogin({ username: "demo", password: "Password123!" });
    await api.authRefresh();
    await api.authMe();
    await api.authLogout();

    await api.dashboardBootstrap("2026-03", "USD");
    await api.dashboardNetWorthChange("2026-03", "USD", "prev_month");
    await api.dashboardSummary("2026-03", "prev_month,prev_year", "USD", true);
    await api.stockHoldingsSummary("2026-03", "USD");
    await api.cashDeposits("2026-03", "USD");
    await api.platformAllocation("2026-03", "USD");
    await api.dashboardGeographyExposure("2026-03", "USD");
    await api.stockExposure("2026-03", "USD");

    await api.categories();
    await api.unmappedTransactions("2026-03");
    await api.unmappedTransactions("2026-03", 7);
    await api.categoryOverride({ transaction_id: 10, category_id: 3 });

    await api.platforms();
    await api.platformOptions();
    await api.createPlatform({
      code: "DBS",
      name: "DBS Bank",
      platform_type: "BANK",
      country: "SG",
      website: "https://dbs.com",
    });

    await api.accounts();
    await api.accountOptions();
    await api.createAccount({
      name: "DBS Savings",
      platform_id: 1,
      platform: "DBS",
      account_type: "BANK",
      currency: "SGD",
      country: "SG",
    });

    await api.currencies();
    await api.createCurrency({ code: "USD", name: "US Dollar", country: "US" });

    await api.spendingSummary("2026-03", "USD");
    await api.cashFlowDetail("2026-03", "USD");
    await api.creditCardSummary("2026-03", "USD");
    await api.creditCardTransactions("2026-03", "USD");

    await api.ingestUpload(12, sampleFile);
    await api.ingestIbkr(12, sampleFile);
    await api.ingestJobs();
    await api.ingestJob(33);
    await api.registerIngestSignature(33, "ibkr_default");

    await api.cryptoWallets();
    await api.cryptoWalletInit({ chain_type: "evm", chain: "ethereum", address: "0xabc" });
    await api.cryptoWalletVerify({
      chain_type: "evm",
      chain: "ethereum",
      address: "0xabc",
      signature: "0xsig",
      verification_id: 1,
    });
    await api.cryptoWalletVerifyOnchain({ address: "SoLAddR", signature: "sig", verification_id: 2 });
    await api.solanaBlockhash();
    await api.solanaSubmit({ tx_b64: "Zm9v" });
    await api.solanaPreflight({ tx_b64: "YmFy" });
    await api.cryptoSummary("USD");
    await api.cryptoRefreshNow("admin-key");
    await api.cryptoAllowlist();
    await api.cryptoAllowlistAdd({ chain: "ethereum", contract_address: "0xabc" });

    await api.marketDataStatus();
    await api.marketDataRuns(10);
    await api.marketDataRefreshNow("admin-key");
    await api.uploadReminders();
    await api.uploadReminderCount();

    await api.dividendsSummary("2026-01", "2026-03", "quarter", "USD", 0.1, "SG:0,US:0.15");
    await api.dividendsByCompany("2026-01", "2026-03", "USD", 0.1, "SG:0");
    await api.dividendsHistory(11, "2026-01", "2026-03", "USD", 0.1, "US:0.15");
    await api.expectedDividendsOverview("2026-01", "2026-03", "USD", 0.1, "US:0.15");

    expect(fetchSpy).toHaveBeenCalled();
    const urls = fetchSpy.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.includes("/dashboard/bootstrap"))).toBe(true);
    expect(urls.some((url) => url.includes("/ingest/upload?account_id=12"))).toBe(true);
    expect(urls.some((url) => url.includes("/crypto/wallets/verify"))).toBe(true);
    expect(urls.some((url) => url.includes("/dividends/expected/overview"))).toBe(true);
  });

  it("retries once after refresh on 401 and updates bearer token", async () => {
    const fetchSpy = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/refresh")) {
        return Promise.resolve(okJson({ access_token: "token-2", token_type: "bearer", expires_in: 3600 }));
      }
      if (!fetchSpy.mock.calls.slice(0, -1).some((call) => String(call[0]).includes("/dashboard/bootstrap"))) {
        return Promise.resolve({
          ok: false,
          status: 401,
          json: () => Promise.resolve({ detail: "expired token" }),
          text: () => Promise.resolve(JSON.stringify({ detail: "expired token" })),
        } satisfies MockResponse);
      }
      return Promise.resolve(okJson({ as_of_month: "2026-03" }));
    });

    vi.stubGlobal("fetch", fetchSpy);
    const { api, setAccessToken } = await import("../lib/api");
    setAccessToken("token-1");

    await api.dashboardBootstrap("2026-03", "USD");

    const dashboardCalls = fetchSpy.mock.calls.filter((call) => String(call[0]).includes("/dashboard/bootstrap"));
    expect(dashboardCalls).toHaveLength(2);

    const firstHeaders = dashboardCalls[0][1]?.headers as Headers;
    const secondHeaders = dashboardCalls[1][1]?.headers as Headers;
    expect(firstHeaders.get("Authorization")).toBe("Bearer token-1");
    expect(secondHeaders.get("Authorization")).toBe("Bearer token-2");
    expect(fetchSpy.mock.calls.some((call) => String(call[0]).includes("/auth/refresh"))).toBe(true);
  });

  it("maps server and network failures to user-facing errors", async () => {
    const failingFetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({}),
        text: () => Promise.resolve("internal"),
      } satisfies MockResponse)
      .mockRejectedValueOnce(new Error("connect ECONNREFUSED"));
    vi.stubGlobal("fetch", failingFetch);
    const { api } = await import("../lib/api");

    await expect(api.health()).rejects.toThrow("Server error. Please try again.");
    await expect(api.health()).rejects.toThrow(/Unable to reach API at/);
  });

  it("covers optional query/header branches and validation formatting fallbacks", async () => {
    let loginCall = 0;
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes("/auth/login")) {
        return okJson({});
      }
      loginCall += 1;
      if (loginCall === 1) {
        return {
          ok: false,
          status: 422,
          json: () => Promise.resolve({ detail: [{ loc: ["body", 3], msg: "bad field" }, { loc: ["body"], msg: "ignored body only" }] }),
          text: () =>
            Promise.resolve(JSON.stringify({ detail: [{ loc: ["body", 3], msg: "bad field" }, { loc: ["body"], msg: "ignored body only" }] })),
        } satisfies MockResponse;
      }
      if (loginCall === 2) {
        return {
          ok: false,
          status: 422,
          json: () => Promise.resolve({ detail: [{ loc: ["body"], msg: "   " }] }),
          text: () => Promise.resolve(JSON.stringify({ detail: [{ loc: ["body"], msg: "   " }] })),
        } satisfies MockResponse;
      }
      if (loginCall === 3) {
        return {
          ok: false,
          status: 400,
          json: () => Promise.resolve({ message: "message fallback" }),
          text: () => Promise.resolve(JSON.stringify({ message: "message fallback" })),
        } satisfies MockResponse;
      }
      if (loginCall === 4) {
        return {
          ok: false,
          status: 400,
          json: () => Promise.resolve({}),
          text: () => Promise.resolve("plain text failure"),
        } satisfies MockResponse;
      }
      return {
        ok: false,
        status: 400,
        json: () => Promise.resolve({}),
        text: () => Promise.resolve(""),
      } satisfies MockResponse;
    });

    vi.stubGlobal("fetch", fetchSpy);
    const { api } = await import("../lib/api");

    await api.dashboardSummary("2026-03", undefined, "USD", false);
    await api.cryptoRefreshNow();
    await api.marketDataRefreshNow();
    await api.dividendsSummary("2026-01", "2026-03", "quarter", "USD", 0.1);
    await api.dividendsByCompany("2026-01", "2026-03", "USD", 0.1);
    await api.dividendsHistory(1, "2026-01", "2026-03", "USD", 0.1);
    await api.expectedDividendsOverview("2026-01", "2026-03", "USD", 0.1);

    await expect(api.authLogin({ username: "a", password: "b" })).rejects.toThrow("bad field");
    await expect(api.authLogin({ username: "a", password: "b" })).rejects.toThrow('{"detail":[{"loc":["body"],"msg":"   "}]}');
    await expect(api.authLogin({ username: "a", password: "b" })).rejects.toThrow("message fallback");
    await expect(api.authLogin({ username: "a", password: "b" })).rejects.toThrow("plain text failure");
    await expect(api.authLogin({ username: "a", password: "b" })).rejects.toThrow("Request failed (400).");

    const called = fetchSpy.mock.calls.map((call) => String(call[0]));
    expect(called.some((url) => url.includes("/dashboard/summary?month=2026-03&base_currency=USD"))).toBe(true);
    expect(called.some((url) => url.includes("/crypto/refresh-now"))).toBe(true);
    expect(called.some((url) => url.includes("/market-data/refresh-now"))).toBe(true);
    expect(called.some((url) => url.includes("/dividends/summary?"))).toBe(true);
  });

  it("covers refresh edge cases", async () => {
    const fetchSpy = vi.fn()
      // Refresh edge case: missing access_token payload.
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "expired" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "expired" })),
      } satisfies MockResponse)
      .mockResolvedValueOnce(okJson({ token_type: "bearer", expires_in: 3600 }))
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "expired again" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "expired again" })),
      } satisfies MockResponse)
      // Refresh network error path.
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "expired" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "expired" })),
      } satisfies MockResponse)
      .mockRejectedValueOnce(new Error("refresh failed"))
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: "expired" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "expired" })),
      } satisfies MockResponse);

    vi.stubGlobal("fetch", fetchSpy);
    const { api, setAccessToken } = await import("../lib/api");
    setAccessToken("expired-token");

    await expect(api.dashboardBootstrap("2026-03", "USD")).rejects.toThrow("expired");
    await expect(api.dashboardBootstrap("2026-03", "USD")).rejects.toThrow("expired");
  });

  it("covers ingest upload helper catch + non-ok branches", async () => {
    const fetchSpy = vi.fn()
      .mockRejectedValueOnce("upload network")
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ detail: "bad upload" }),
        text: () => Promise.resolve("bad upload"),
      } satisfies MockResponse)
      .mockRejectedValueOnce("ibkr network")
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ detail: "bad ibkr" }),
        text: () => Promise.resolve("bad ibkr"),
      } satisfies MockResponse);
    vi.stubGlobal("fetch", fetchSpy);
    const { api, setAccessToken } = await import("../lib/api");
    setAccessToken(null);
    const file = new File(["x"], "sample.csv", { type: "text/csv" });
    await expect(api.ingestUpload(1, file)).rejects.toThrow(/Unable to reach API at/);
    await expect(api.ingestUpload(1, file)).rejects.toThrow("bad upload");
    await expect(api.ingestIbkr(1, file)).rejects.toThrow(/Unable to reach API at/);
    await expect(api.ingestIbkr(1, file)).rejects.toThrow("bad ibkr");
  });
});
