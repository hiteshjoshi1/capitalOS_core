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
  total_crypto_usd: 8400,
  total_crypto_base: 11200,
  base_currency: "SGD",
  eth_exposure_usd: 8000,
  eth_exposure_base: 10667,
  token_exposure_usd: 400,
  token_exposure_base: 533,
  token_count: 2,
  priced_token_count: 2,
  eth: { balance: 1.2345, value_usd: 8000, value_base: 10667 },
  sol: { balance: 10, value_usd: 400, value_base: 533 },
  top5_holdings: [
    { symbol: "ETH", chain: "ethereum", amount: 1.2345, value_usd: 8000, value_base: 10667 },
    { symbol: "SOL", chain: "solana", amount: 10, value_usd: 400, value_base: 533 },
  ],
  top_holdings: [
    { symbol: "ETH", chain: "ethereum", amount: 1.2345, value_usd: 8000, value_base: 10667, asset_class: "CRYPTO" },
    { symbol: "SOL", chain: "solana", amount: 10, value_usd: 400, value_base: 533, asset_class: "CRYPTO" },
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
    },
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

    expect(await screen.findByText("Overview")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toHaveValue("2026-02");
    expect(screen.getByLabelText("Base currency")).toHaveValue("SGD");
    expect(mockApi.cryptoSummary).toHaveBeenCalledWith("SGD");
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
      wallet_exposure: [],
      wallet_chain_exposure: [],
      refresh_triggered: true,
      is_stale: true,
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

    expect(await screen.findByText("Top Holdings")).toBeInTheDocument();
    expect(screen.queryByText("DUST")).not.toBeInTheDocument();
    expect(screen.getByText(/Stale/)).toBeInTheDocument();
    expect(screen.getByText(/\(refreshing\)/)).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /Show <\$10 tokens/i }));
    await waitFor(() => {
      expect(screen.getByText("DUST")).toBeInTheDocument();
    });
  });

  it("shows fallback rows when there are no holdings", async () => {
    mockApi.cryptoSummary.mockResolvedValueOnce({
      ...cryptoSummaryFixture,
      top_holdings: [],
      wallet_exposure: [],
      wallet_chain_exposure: [],
      last_refreshed_at: null,
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
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.queryByText("Exposure by Wallet")).not.toBeInTheDocument();
    expect(screen.queryByText("Exposure by Wallet + Chain")).not.toBeInTheDocument();
  });
});
