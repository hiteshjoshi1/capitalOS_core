import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import SinceLastVisitStrip from "../components/SinceLastVisitStrip";
import StockMonthChange from "../components/StockMonthChange";
import { api, type SinceLastVisit, type StockMonthChange as Change } from "../lib/api";
import { hasNews } from "../lib/sinceLastVisit";
import { clearApiCache } from "../lib/useApiResource";
import InboxBell from "../components/InboxBell";
import type { InboxResponse } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: { sinceLastVisit: vi.fn(), markVisit: vi.fn(), operationsInbox: vi.fn() },
}));
const mockApi = vi.mocked(api, true);

const visit = (over: Partial<SinceLastVisit> = {}): SinceLastVisit => ({
  first_visit: false,
  base_currency: "SGD",
  seen_at: "2026-11-10T13:40:00+00:00",
  net_worth_then: 1000,
  net_worth_now: 2234,
  change: 1234,
  imports_since: 2,
  needs_action: 1,
  ...over,
});

afterEach(() => {
  vi.clearAllMocks();
  clearApiCache();
});

const inboxOf = (count: number): InboxResponse => ({
  as_of: "2026-11-12",
  count,
  items: Array.from({ length: count }, (_, i) => ({
    id: `item:${i}`, kind: "source_overdue", severity: "medium", title: `Item ${i}`, detail: null, source: null,
    action: { label: "Open", route: "/operations", params: {}, run: null, admin_only: false },
  })),
  all_good: [],
  recent_activity: [],
});

describe("Since your last visit (#408, U3)", () => {
  it("has news only for a real change, imports or actions", () => {
    expect(hasNews(null)).toBe(false);
    expect(hasNews({ first_visit: true, base_currency: "SGD" })).toBe(false);
    expect(hasNews(visit({ change: 0.4, imports_since: 0, needs_action: 0 }))).toBe(false);
    expect(hasNews(visit({ change: 0, imports_since: 1, needs_action: 0 }))).toBe(true);
    expect(hasNews(visit({ change: null, imports_since: 0, needs_action: 3 }))).toBe(true);
  });

  it("shows the change, imports and actions, records the visit, and dismiss moves the mark", async () => {
    mockApi.sinceLastVisit.mockResolvedValue(visit());
    mockApi.operationsInbox.mockResolvedValue(inboxOf(1));
    mockApi.markVisit.mockResolvedValue({ moved: true, seen_at: "2026-11-12T01:00:00+00:00" });
    render(
      <MemoryRouter>
        <SinceLastVisitStrip baseCurrency="SGD" />
      </MemoryRouter>,
    );
    const strip = await screen.findByRole("complementary", { name: "Since your last visit" });
    expect(strip).toHaveTextContent("+S$ 1,234 net worth");
    expect(strip).toHaveTextContent("2 imports");
    expect(screen.getByRole("link", { name: "1 needs action" })).toHaveAttribute("href", "/operations");
    await waitFor(() => expect(mockApi.markVisit).toHaveBeenCalledWith("SGD"));

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(mockApi.markVisit).toHaveBeenLastCalledWith("SGD", true);
    expect(screen.queryByRole("complementary", { name: "Since your last visit" })).not.toBeInTheDocument();
  });

  it("counts what needs action from the bell's inbox, so the two always agree (#475, V22)", async () => {
    // The visit reply counted 3 when it was built; the inbox (the bell) now has 2.
    mockApi.sinceLastVisit.mockResolvedValue(visit({ needs_action: 3 }));
    mockApi.markVisit.mockResolvedValue({ moved: false, seen_at: "2026-11-10T13:40:00+00:00" });
    mockApi.operationsInbox.mockResolvedValue(inboxOf(2));
    render(
      <MemoryRouter>
        <InboxBell narrow />
        <SinceLastVisitStrip baseCurrency="SGD" />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "2 need action" })).toHaveAttribute("href", "/operations");
    expect(screen.getByRole("link", { name: "2 items need you" })).toBeInTheDocument();
    expect(screen.queryByText(/3 need action/)).not.toBeInTheDocument();
    expect(mockApi.operationsInbox).toHaveBeenCalledTimes(1); // one request for both
  });

  it("falls back to the visit's own count when the inbox can't load", async () => {
    mockApi.sinceLastVisit.mockResolvedValue(visit({ change: null, imports_since: 0, needs_action: 3 }));
    mockApi.markVisit.mockResolvedValue({ moved: false, seen_at: "x" });
    mockApi.operationsInbox.mockRejectedValue(new Error("inbox down"));
    render(
      <MemoryRouter>
        <SinceLastVisitStrip baseCurrency="SGD" />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "3 need action" })).toBeInTheDocument();
  });

  it("drops the strip when its only news was actions the inbox no longer has", async () => {
    mockApi.sinceLastVisit.mockResolvedValue(visit({ change: null, imports_since: 0, needs_action: 2 }));
    mockApi.markVisit.mockResolvedValue({ moved: false, seen_at: "x" });
    mockApi.operationsInbox.mockResolvedValue(inboxOf(0));
    render(
      <MemoryRouter>
        <SinceLastVisitStrip baseCurrency="SGD" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mockApi.markVisit).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Since your last visit" })).not.toBeInTheDocument());
  });

  it("shows nothing on a first visit", async () => {
    mockApi.sinceLastVisit.mockResolvedValue({ first_visit: true, base_currency: "SGD" });
    mockApi.operationsInbox.mockResolvedValue(inboxOf(0));
    mockApi.markVisit.mockResolvedValue({ moved: true, seen_at: "x" });
    const { container } = render(
      <MemoryRouter>
        <SinceLastVisitStrip baseCurrency="SGD" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mockApi.markVisit).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Crypto change split (#408, U9)", () => {
  const change: Change = {
    abs: 2400,
    pct: 0.8,
    price_effect: 600,
    quantity_effect: 1800,
    fx_effect: 0,
    unsplit: 0,
    compare_value: 3000,
    end_value: 5400,
    compare_month: "2026-04",
    baseline_missing: false,
    side: "held",
    start_quantity: 2,
    end_quantity: 3,
    start_price: 1500,
    end_price: 1800,
    price_currency: "USD",
    start_rate: 1,
    end_rate: 1,
  };

  it("names the token, not shares, and says added rather than bought", () => {
    render(<StockMonthChange change={change} currency="USD" compareLabel="Apr 2026" symbol="ETH" unit="ETH" />);
    const toggle = screen.getByRole("button", { name: /ETH since Apr 2026/ });
    expect(toggle).toHaveTextContent("added");
    expect(toggle.getAttribute("title")).toContain("added 1 ETH");
    expect(toggle.getAttribute("title")).not.toContain("shares");
  });
});
