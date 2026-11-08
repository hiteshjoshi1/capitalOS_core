import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RealisedPnlCard from "../components/RealisedPnlCard";
import { api, type RealisedPnl } from "../lib/api";

vi.mock("../lib/api", () => ({ api: { realisedPnl: vi.fn() } }));
const mockApi = vi.mocked(api, true);

// Synthetic sales only.
const fixture: RealisedPnl = {
  base_currency: "SGD",
  month: { realised: 1250.5, sales: 2, cost_unknown: 1, fx_missing_currencies: [], sources: { ibkr: 1, cost_unknown: 1 } },
  year_to_date: { realised: -300, sales: 4, cost_unknown: 1, fx_missing_currencies: ["JPY"], sources: { ibkr: 2, fifo: 1, cost_unknown: 1 } },
  sales: [
    { trade_date: "2026-03-05", symbol: "AAA", platform: "IBKR", quantity: 5, proceeds: 649, cost: 400, realised: 930, currency: "USD", realised_base: 1250.5, source: "ibkr", fx_missing: false },
    { trade_date: "2026-03-20", symbol: "BBB", platform: "IBKR", quantity: 2, proceeds: 300, cost: null, realised: null, currency: "SGD", realised_base: null, source: "cost_unknown", fx_missing: false },
  ],
};

describe("RealisedPnlCard (#293)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.realisedPnl.mockResolvedValue(fixture);
  });

  it("shows the month and year to date, signed with arrows, and what was left out", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    const card = await screen.findByRole("region", { name: "Realised profit and loss" });
    expect(mockApi.realisedPnl).toHaveBeenCalledWith("2026-03", "SGD");
    expect(card).toHaveTextContent("▲ +S$ 1,251"); // D-69: whole units from 1,000
    expect(card).toHaveTextContent("2 sales");
    expect(card).toHaveTextContent("2026 to date");
    expect(card).toHaveTextContent("▼ -S$ 300.00");
    expect(card).toHaveTextContent("1 sale with no known buy cost: left out");
    expect(card).toHaveTextContent("No exchange rate for JPY: left out");
    expect(card).toHaveTextContent("IBKR's figure (2) · FIFO from your trades (1) · cost unknown (1)");
  });

  it("lists the month's sales on demand, naming the source and never showing 0 for an unknown cost", async () => {
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    fireEvent.click(await screen.findByRole("button", { name: /Show .* sales/ }));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("AAA");
    expect(items[0]).toHaveTextContent("IBKR's figure");
    expect(items[0]).toHaveTextContent("+USD 930.00"); // the trade currency next to the base amount
    expect(within(items[1]).getAllByText("cost unknown").length).toBeGreaterThan(0);
    expect(items[1]).not.toHaveTextContent("S$ 0");
  });

  it("says No sales when there were none", async () => {
    const none = { realised: 0, sales: 0, cost_unknown: 0, fx_missing_currencies: [], sources: {} };
    mockApi.realisedPnl.mockResolvedValue({ base_currency: "SGD", month: none, year_to_date: none, sales: [] });
    render(<RealisedPnlCard month="2026-03" baseCurrency="SGD" />);
    const card = await screen.findByRole("region", { name: "Realised profit and loss" });
    expect(within(card).getAllByText("No sales")).toHaveLength(2);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
