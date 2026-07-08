import { render, screen, waitFor } from "@testing-library/react";
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
  },
}));

const mockApi = vi.mocked(api, true);

const cryptoSummaryFixture: CryptoSummary = {
  month: "2026-02",
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
    expect(screen.getByText(/Holdings as of 2026-02-06/)).toBeInTheDocument();
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

    expect(await screen.findByText("API error")).toBeInTheDocument();
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
    expect(screen.getByText(/Showing 1 of 2 holdings · 1 hidden under \$10/)).toBeInTheDocument();
    expect(screen.getByText(/stale\)/)).toBeInTheDocument();
    expect(screen.getByText(/refreshing/)).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /Show holdings under \$10/i }));
    await waitFor(() => {
      expect(screen.getByText("DUST")).toBeInTheDocument();
    });
    expect(screen.getByText(/Showing all 2 holdings, including dust under \$10/)).toBeInTheDocument();
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
