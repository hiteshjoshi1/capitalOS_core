import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { controlledCalls } from "./raceHelpers";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import CryptoHoldings from "../routes/CryptoHoldings";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { CryptoSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    cryptoSummary: vi.fn(),
    cryptoSetTokenVisibility: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const cryptoSummaryFixture: CryptoSummary = {
  month: "2026-02",
  is_live: true,
  compare_month: "2026-01",
  snapshot_day: 6,
  snapshot_as_of: "2026-02-06",
  total_crypto_usd: 8400,
  total_crypto_base: 11200,
  snapshot_total_base: 10400,
  snapshot_total_usd: 7800,
  snapshot_delta_base: 800,
  snapshot_delta_pct: 800 / 10400,
  base_currency: "SGD",
  eth_exposure_usd: 8000,
  eth_exposure_base: 10667,
  token_exposure_usd: 400,
  token_exposure_base: 533,
  token_count: 2,
  priced_token_count: 2,
  trend: [
    { month: "2025-09", value: null },
    { month: "2025-10", value: null },
    { month: "2025-11", value: 9000 },
    { month: "2025-12", value: 9500 },
    { month: "2026-01", value: 10000 },
    { month: "2026-02", value: 10400 },
  ],
  eth: { balance: 1.2345, value_usd: 8000, value_base: 10667 },
  sol: { balance: 10, value_usd: 400, value_base: 533 },
  top5_holdings: [
    { symbol: "ETH", chain: "ethereum", amount: 1.2345, value_usd: 8000, value_base: 10667 },
    { symbol: "SOL", chain: "solana", amount: 10, value_usd: 400, value_base: 533 },
  ],
  top_holdings: [
    {
      symbol: "ETH",
      chain: "ethereum",
      amount: 1.2345,
      value_usd: 8000,
      value_base: 10667,
      asset_class: "CRYPTO",
      price_change_usd: 50,
      price_provider: "defillama,coingecko",
      value_change_base: 267,
      value_change_pct: 0.025,
      snapshot_delta_base: 600,
      snapshot_delta_pct: 0.06,
    },
    {
      symbol: "SOL",
      chain: "solana",
      amount: 10,
      value_usd: 400,
      value_base: 533,
      asset_class: "CRYPTO",
      price_change_usd: -2,
      price_provider: "helius",
      value_change_base: -20,
      value_change_pct: -0.04,
      snapshot_delta_base: 200,
      snapshot_delta_pct: 0.1,
    },
  ],
  wallet_exposure: [
    {
      wallet_id: "wallet-1",
      chain_type: "evm",
      chain: "ethereum",
      address: "0x1234567890abcdef",
      label: "Main Wallet",
      total_usd: 8400,
      total_base: 11200,
      percent: 100,
    },
  ],
  chain_exposure: [
    { chain: "ethereum", total_usd: 8000, total_base: 10667, percent: 95.2 },
    { chain: "solana", total_usd: 400, total_base: 533, percent: 4.8 },
  ],
  wallet_chain_exposure: [
    {
      wallet_id: "wallet-1",
      chain: "ethereum",
      total_usd: 8000,
      total_base: 10667,
    },
  ],
  last_refreshed_at: "2026-02-06T00:00:00+00:00",
  holdings_as_of: "2026-02-06T00:00:00+00:00",
  price_as_of: "2026-02-06T01:00:00+00:00",
  stale_holdings: false,
  stale_prices: false,
  is_stale: false,
  refresh_triggered: false,
};

describe("CryptoHoldings route", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("shows the shared month selector alongside crypto details", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-02");
    mockApi.cryptoSummary.mockResolvedValueOnce(cryptoSummaryFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("CURRENT CRYPTO VALUE")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toHaveValue("2026-02");
    expect(screen.getByLabelText("Base currency")).toHaveValue("SGD");
    expect(mockApi.cryptoSummary).toHaveBeenCalledWith("2026-02", "SGD");
    const chainHeading = screen.getByText("Chain mix");
    const walletHeading = screen.getByText("Wallet mix");
    const trendHeading = screen.getByText("Six-month value trend");
    const topHoldingsHeading = screen.getByText("Top holdings");
    expect(trendHeading).toBeInTheDocument();
    expect(screen.getByLabelText("Six-month crypto trend")).toBeInTheDocument();
    expect(chainHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(walletHeading.compareDocumentPosition(trendHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(trendHeading.compareDocumentPosition(topHoldingsHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Sep '25")).not.toBeInTheDocument();
    expect(screen.queryByText("Oct '25")).not.toBeInTheDocument();
    expect(screen.getAllByText("Nov '25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("S$ 9K").length).toBeGreaterThan(0);
    expect(chainHeading).toBeInTheDocument();
    expect(walletHeading).toBeInTheDocument();
    expect(screen.getByText(/fresh\)/)).toBeInTheDocument();
    expect(screen.getByText(/Holdings as of 6 Feb 2026/)).toBeInTheDocument();
  });

  it("shows API error state when fetch fails", async () => {
    mockApi.cryptoSummary.mockRejectedValueOnce(new Error("crypto unavailable"));

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Couldn't load crypto holdings")).toBeInTheDocument();
    expect(screen.getByText("crypto unavailable")).toBeInTheDocument();
  });

  it("filters dust holdings by default and shows them when toggled", async () => {
    const dusty: CryptoSummary = {
      ...cryptoSummaryFixture,
      top_holdings: [
        { symbol: "ETH", chain: "ethereum", amount: 1.1, value_usd: 3500, value_base: 4700, asset_class: "CRYPTO" },
        { symbol: "DUST", chain: "ethereum", amount: 10, value_usd: 5, value_base: 7, asset_class: "CRYPTO" },
      ],
      chain_exposure: [],
      wallet_exposure: [],
      wallet_chain_exposure: [],
      refresh_triggered: true,
      is_stale: true,
      stale_holdings: true,
      stale_prices: false,
    };
    mockApi.cryptoSummary.mockResolvedValueOnce(dusty);

    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Top holdings")).toBeInTheDocument();
    expect(screen.queryByText("DUST")).not.toBeInTheDocument();
    expect(screen.getByText(/Showing 1 of 2 holdings · 1 hidden under USD 10/)).toBeInTheDocument();
    expect(screen.getByText(/stale\)/)).toBeInTheDocument();
    expect(screen.getByText(/refreshing/)).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /Show holdings under USD 10/i }));
    await waitFor(() => {
      expect(screen.getByText("DUST")).toBeInTheDocument();
    });
    expect(screen.getByText(/Showing all 2 holdings, including dust under USD 10/)).toBeInTheDocument();
  });

  it("shows Coinbase exchange holdings and wallet exposure from the crypto summary", async () => {
    const coinbase: CryptoSummary = {
      ...cryptoSummaryFixture,
      total_crypto_usd: 15900,
      total_crypto_base: 15900,
      base_currency: "USD",
      top_holdings: [
        {
          symbol: "BTC",
          chain: "coinbase",
          amount: 0.125,
          value_usd: 7500,
          value_base: 7500,
          asset_class: "CRYPTO",
          wallet_id: "coinbase-wallet",
          wallet_label: "Coinbase",
        },
        ...cryptoSummaryFixture.top_holdings,
      ],
      chain_exposure: [
        { chain: "coinbase", total_usd: 7500, total_base: 7500, percent: 47.2 },
        ...(cryptoSummaryFixture.chain_exposure ?? []),
      ],
      wallet_exposure: [
        {
          wallet_id: "coinbase-wallet",
          chain_type: "exchange",
          chain: "coinbase",
          address: "coinbase:1:default",
          label: "Coinbase",
          total_usd: 7500,
          total_base: 7500,
          percent: 47.2,
        },
        ...(cryptoSummaryFixture.wallet_exposure ?? []),
      ],
    };
    mockApi.cryptoSummary.mockResolvedValueOnce(coinbase);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("BTC")).toBeInTheDocument();
    expect(screen.getByText("COINBASE")).toBeInTheDocument();
    expect(screen.getAllByText("Coinbase").length).toBeGreaterThan(0);
  });

  it("shows fallback rows when there are no holdings", async () => {
    mockApi.cryptoSummary.mockResolvedValueOnce({
      ...cryptoSummaryFixture,
      top_holdings: [],
      chain_exposure: [],
      wallet_exposure: [],
      wallet_chain_exposure: [],
      last_refreshed_at: null,
      holdings_as_of: null,
      price_as_of: null,
      eth_exposure_usd: undefined,
      eth_exposure_base: undefined,
      token_exposure_usd: undefined,
      token_exposure_base: undefined,
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("No crypto holdings yet.")).toBeInTheDocument();
    expect(screen.getByText("Wallet mix")).toBeInTheDocument();
    expect(screen.getAllByText("No exposure data yet.").length).toBeGreaterThan(0);
  });
});

// #148: a slow earlier month never renders under a later one.
describe("CryptoHoldings races", () => {
  it("shows the later month even when the earlier month's reply lands last", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-02");
    const summaries = controlledCalls<CryptoSummary>();
    mockApi.cryptoSummary.mockImplementation(summaries.impl as typeof api.cryptoSummary);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );
    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-01" } });
    const feb = summaries.find((a) => a[0] === "2026-02");
    const jan = summaries.find((a) => a[0] === "2026-01");

    await act(async () => jan.resolve({ ...cryptoSummaryFixture, month: "2026-01", is_live: false }));
    expect(await screen.findByText("CRYPTO VALUE — 2026-01")).toBeInTheDocument();
    await act(async () => feb.resolve({ ...cryptoSummaryFixture, month: "2026-02", is_live: false }));
    expect(screen.queryByText("CRYPTO VALUE — 2026-02")).not.toBeInTheDocument();
    expect(screen.getByText("CRYPTO VALUE — 2026-01")).toBeInTheDocument();
    await waitFor(() => expect(feb.signal?.aborted).toBe(true));
  });

  it("says there is no comparison when the compare month has no wallet data (#224)", async () => {
    mockApi.cryptoSummary.mockResolvedValueOnce({
      ...cryptoSummaryFixture,
      snapshot_total_base: 0,
      snapshot_total_usd: 0,
      snapshot_delta_base: 11200,
      snapshot_delta_pct: null,
      snapshot_missing: true,
      snapshot_missing_reason: "no_data",
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("no comparison: no data for Jan 2026")).toBeInTheDocument();
  });

  it("names a missing exchange rate as the reason (#224, D-30)", async () => {
    mockApi.cryptoSummary.mockResolvedValueOnce({
      ...cryptoSummaryFixture,
      snapshot_total_base: 0,
      snapshot_missing: true,
      snapshot_missing_reason: "no_fx_rate",
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText("no comparison: no exchange rate for Jan 2026")).toBeInTheDocument();
  });

  it("shows each holding's change with the % in the same (base) currency as the amount (#224)", async () => {
    mockApi.cryptoSummary.mockResolvedValueOnce(cryptoSummaryFixture);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    // SOL: S$ 533 now, -S$ 20.00 vs last month -> -3.6% of S$ 553, not the USD -4.0%.
    const sol = (await screen.findByText("-S$ 20.00 (-3.6%)")).closest(".delta");
    expect(sol).toHaveClass("delta--down");
    expect(sol).toHaveTextContent("▼");
    expect(screen.queryByText(/-4\.0%/)).not.toBeInTheDocument();
    // The header chip: +S$ 800 on S$ 10,400.
    expect(document.querySelector(".coHeroValueRow .deltaChip")).toHaveTextContent("▲+7.7%");
  });

  // #232: the previous figure names its month and the date of its snapshot, live or past.
  it.each([
    ["live", true],
    ["past", false],
  ])("dates the compare month's figure (%s, #232)", async (_label, isLive) => {
    mockApi.cryptoSummary.mockResolvedValueOnce({
      ...cryptoSummaryFixture,
      is_live: isLive,
      as_of: "2026-03-01T00:00:00+00:00",
      snapshot_as_of: "2026-01-30",
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByText(/vs Jan 2026 \(30 Jan 2026\)/)).toBeInTheDocument();
  });

  it("hides unknown tokens by default, shows them on request, and marks one as not spam (#342)", async () => {
    const SPAM = "0x1111111111111111111111111111111111111111";
    const withSpam: CryptoSummary = {
      ...cryptoSummaryFixture,
      hidden_token_count: 1,
      top_holdings: [
        { symbol: "ETH", chain: "ethereum", amount: 1.1, value_usd: 3500, value_base: 4700, asset_class: "CRYPTO",
          token_key: null, contract_or_mint: null, hidden: false },
        { symbol: "SOL", chain: "ethereum", amount: 5, value_usd: 0, value_base: 0, asset_class: "CRYPTO",
          contract_or_mint: SPAM, token_key: `ethereum:${SPAM}`, unknown_token: true, hidden: true,
          hidden_reason: "unknown_token", visibility_override: null },
      ],
      chain_exposure: [],
      wallet_exposure: [],
      wallet_chain_exposure: [],
    };
    mockApi.cryptoSummary.mockResolvedValue(withSpam);
    mockApi.cryptoSetTokenVisibility.mockResolvedValueOnce({ overrides: [] });

    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <MemoryRouter>
          <CryptoHoldings />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Top holdings")).toBeInTheDocument();
    expect(screen.queryByText("Unknown token")).not.toBeInTheDocument();
    expect(screen.getByText(/1 unknown or hidden token \(no price source/)).toBeInTheDocument();
    // Native coins have no Hide/Not spam control (no contract to key on).
    expect(screen.queryByRole("button", { name: /Hide ETH/ })).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Show hidden (1)" });
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Unknown token")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show SOL on ethereum" }));
    await waitFor(() =>
      expect(mockApi.cryptoSetTokenVisibility).toHaveBeenCalledWith({ chain: "ethereum", contract_or_mint: SPAM, visibility: "shown" }),
    );
  });
});
