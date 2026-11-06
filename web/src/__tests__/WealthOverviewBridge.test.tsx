import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WealthOverview from "../routes/WealthOverview";
import { api } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

// #240: the "This month" bridge sits right below the Overview hero and follows the
// shared selected month and base currency. (The card itself: MonthBridgeCard.test.tsx.)

vi.mock("../lib/api", () => ({
  api: {
    dashboardBootstrap: vi.fn(),
    dashboardSummary: vi.fn(),
    platformAllocation: vi.fn(),
    spendingSummary: vi.fn(),
    netWorthSinceUpdate: vi.fn(),
    monthBridge: vi.fn(),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn(() => () => {}),
}));

const mockApi = vi.mocked(api, true);
const nw = { total: 1000, cash: 100, stocks_funds: 900, crypto: 0, liabilities: 0 };

describe("Overview: This month bridge", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
    window.localStorage.clear();
    mockApi.dashboardBootstrap.mockImplementation(((month: string, currency: string) =>
      Promise.resolve({
        as_of_month: month,
        base_currency: currency,
        is_live: false,
        net_worth: nw,
        current_net_worth: nw,
        net_worth_boundary_at: "2026-05-01T00:00:00+00:00",
      })) as never);
    mockApi.dashboardSummary.mockReturnValue(new Promise(() => {}) as never);
    mockApi.platformAllocation.mockReturnValue(new Promise(() => {}) as never);
    mockApi.spendingSummary.mockReturnValue(new Promise(() => {}) as never);
    mockApi.netWorthSinceUpdate.mockReturnValue(new Promise(() => {}) as never);
    mockApi.monthBridge.mockReturnValue(new Promise(() => {}) as never);
  });

  it("asks for the selected month and puts the card between the hero and the allocation", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-04");
    render(
      <MemoryRouter>
        <WealthOverview />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mockApi.monthBridge).toHaveBeenCalledWith("2026-04", "SGD"));
    const card = await screen.findByTestId("month-bridge");
    const hero = document.querySelector(".coHeroCard");
    const allocation = screen.getByText("Where the money sits");
    expect(hero).not.toBeNull();
    expect(hero!.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(card.compareDocumentPosition(allocation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
