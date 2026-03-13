import { render, screen, within } from "@testing-library/react";
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
    const nav = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(within(nav).getByRole("link", { name: "Ingest" })).toHaveAttribute("href", "/ingest");
    expect(screen.getByLabelText("Month")).toHaveValue("2026-02");
    expect(screen.getByLabelText("Base currency")).toHaveValue("SGD");
    expect(mockApi.cryptoSummary).toHaveBeenCalledWith("SGD");
  });
});
