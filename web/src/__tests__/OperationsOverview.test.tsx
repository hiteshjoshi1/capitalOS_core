import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import OperationsOverview from "../routes/OperationsOverview";
import { api } from "../lib/api";
import type { Account, InboxItem, InboxResponse } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

vi.mock("../lib/api", () => ({
  api: {
    operationsInbox: vi.fn(),
    accounts: vi.fn(),
    marketDataRefreshNow: vi.fn(),
    ibkrFlexImportNow: vi.fn(),
    cryptoRefreshNow: vi.fn(),
    fxBackfill: vi.fn(),
    sourceFreshness: vi.fn(),
  },
}));

const authState = { user: { id: 1, username: "demo", is_admin: true } as { id: number; username: string; is_admin: boolean } };
vi.mock("../context/useAuth", () => ({ useAuth: () => authState }));

const mockApi = vi.mocked(api, true);

const ibkr: Account = { id: 9, name: "IBKR", platform: "IBKR", account_type: "BROKER", currency: "USD" };

function item(partial: Partial<InboxItem> & Pick<InboxItem, "id" | "kind" | "title">): InboxItem {
  return { severity: "medium", detail: null, action: null, source: null, ...partial };
}

const busyInbox: InboxResponse = {
  as_of: "2026-11-08",
  count: 4,
  items: [
    item({
      id: "job:ibkr_flex",
      kind: "job_failing",
      severity: "high",
      title: "IBKR Flex import is failing",
      detail: "3 failed runs in a row",
      action: { label: "Refresh IBKR", route: null, params: {}, run: "refresh_ibkr", admin_only: false },
    }),
    item({
      id: "import:4",
      kind: "unknown_format",
      title: "Synthetic Bank: file format not recognised",
      action: { label: "Fix format", route: "/ingest", params: { job: "4" }, run: null, admin_only: false },
    }),
    item({
      id: "fx:gap",
      kind: "fx_gap",
      title: "Past exchange rates missing for 12 days",
      action: { label: "Fetch past rates", route: null, params: {}, run: "fx_backfill", admin_only: true },
    }),
    item({
      id: "unmapped",
      kind: "unmapped_transactions",
      severity: "low",
      title: "5 transactions without a category",
      action: { label: "Map transactions", route: "/cash-flow/map-transactions", params: {}, run: null, admin_only: false },
    }),
  ],
  all_good: ["8 sources on time", "All 12 quotes fresh"],
  recent_activity: [
    { kind: "import", title: "Imported a statement", meta: "42 transactions", occurred_at: "2026-11-07" },
  ],
};

const quietInbox: InboxResponse = { ...busyInbox, count: 0, items: [] };

function renderPage() {
  return render(
    <MemoryRouter>
      <OperationsOverview />
    </MemoryRouter>,
  );
}

describe("Data Hub Inbox (#316)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearApiCache();
    authState.user = { id: 1, username: "demo", is_admin: true };
    mockApi.accounts.mockResolvedValue([ibkr]);
    mockApi.sourceFreshness.mockResolvedValue({ as_of: "2026-11-08", overdue_count: 0, cadences: [], sources: [] });
  });

  it("lists what needs you first, each with its action", async () => {
    mockApi.operationsInbox.mockResolvedValue(busyInbox);
    renderPage();
    const heading = await screen.findByRole("heading", { name: /Needs you/ });
    expect(heading).toHaveTextContent("4");
    const rows = screen.getAllByRole("listitem").filter((li) => li.className.includes("inboxItem"));
    expect(rows.map((r) => r.querySelector(".inboxItemTitle")?.textContent)).toEqual([
      "UrgentIBKR Flex import is failing",
      "Needs a lookSynthetic Bank: file format not recognised",
      "Needs a lookPast exchange rates missing for 12 days",
      "When you can5 transactions without a category",
    ]);
    expect(screen.getByRole("link", { name: "Fix format" })).toHaveAttribute("href", "/ingest?job=4");
    expect(screen.getByRole("link", { name: "Map transactions" })).toHaveAttribute("href", "/cash-flow/map-transactions");
  });

  it("runs an item's refresh in place and reloads the list", async () => {
    mockApi.operationsInbox.mockResolvedValueOnce(busyInbox).mockResolvedValue(quietInbox);
    mockApi.ibkrFlexImportNow.mockResolvedValue({ counts: { positions: 7 } } as never);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Refresh IBKR" }));
    await waitFor(() => expect(mockApi.ibkrFlexImportNow).toHaveBeenCalledWith(9));
    expect(await screen.findByText("IBKR: imported 7 positions.")).toBeInTheDocument();
    expect(await screen.findByText(/Nothing needs you/)).toBeInTheDocument();
  });

  it("shows a non-admin who can fix a shared-data item, without the button", async () => {
    authState.user = { id: 2, username: "viewer", is_admin: false };
    mockApi.operationsInbox.mockResolvedValue(busyInbox);
    renderPage();
    await screen.findByRole("heading", { name: /Needs you/ });
    expect(screen.queryByRole("button", { name: "Fetch past rates" })).not.toBeInTheDocument();
    expect(screen.getByText("An admin can fix this")).toBeInTheDocument();
  });

  it("collapses what's fine and shows the latest activity in one line", async () => {
    mockApi.operationsInbox.mockResolvedValue(quietInbox);
    renderPage();
    expect(await screen.findByText(/Nothing needs you/)).toBeInTheDocument();
    const good = screen.getByText(/All good \(2\)/).closest("details");
    expect(good).not.toHaveAttribute("open");
    expect(within(good as HTMLElement).getByText("8 sources on time")).toBeInTheDocument();
    expect(screen.getByText(/Latest: Imported a statement/)).toBeInTheDocument();
  });

  it("Refresh all runs every refresh the user may run; the menu runs one", async () => {
    mockApi.operationsInbox.mockResolvedValue(quietInbox);
    mockApi.marketDataRefreshNow.mockResolvedValue({ exchanges: ["SGX"] } as never);
    mockApi.ibkrFlexImportNow.mockResolvedValue({ counts: { positions: 1 } } as never);
    mockApi.cryptoRefreshNow.mockResolvedValue({ wallets_refreshed: 2 } as never);
    mockApi.fxBackfill.mockResolvedValue({ status: "up_to_date", fetched_requests: 0, remaining_requests: 0 } as never);
    renderPage();
    await screen.findByText(/Nothing needs you/);
    fireEvent.click(screen.getByRole("button", { name: "Refresh all" }));
    await waitFor(() => expect(mockApi.fxBackfill).toHaveBeenCalled());
    expect(mockApi.marketDataRefreshNow).toHaveBeenCalledTimes(1);
    expect(mockApi.cryptoRefreshNow).toHaveBeenCalledTimes(1);
    expect(mockApi.ibkrFlexImportNow).toHaveBeenCalledWith(9);

    vi.clearAllMocks();
    mockApi.operationsInbox.mockResolvedValue(quietInbox);
    mockApi.cryptoRefreshNow.mockResolvedValue({ wallets_refreshed: 2 } as never);
    await screen.findByRole("button", { name: "Refresh all" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh all" })).not.toBeDisabled());
    fireEvent.click(within(screen.getByRole("group", { name: "Refresh one source" })).getByRole("button", { name: "Crypto wallets" }));
    await waitFor(() => expect(mockApi.cryptoRefreshNow).toHaveBeenCalledTimes(1));
    expect(mockApi.marketDataRefreshNow).not.toHaveBeenCalled();
  });

  it("a non-admin's Refresh all leaves out the shared-data refreshes", async () => {
    authState.user = { id: 2, username: "viewer", is_admin: false };
    mockApi.operationsInbox.mockResolvedValue(quietInbox);
    mockApi.ibkrFlexImportNow.mockResolvedValue({ counts: { positions: 1 } } as never);
    mockApi.cryptoRefreshNow.mockResolvedValue({ wallets_refreshed: 0 } as never);
    renderPage();
    await screen.findByText(/Nothing needs you/);
    fireEvent.click(screen.getByRole("button", { name: "Refresh all" }));
    await waitFor(() => expect(mockApi.cryptoRefreshNow).toHaveBeenCalled());
    expect(mockApi.marketDataRefreshNow).not.toHaveBeenCalled();
    expect(mockApi.fxBackfill).not.toHaveBeenCalled();
  });

  it("an overdue upload source opens Upload prefilled (#278)", async () => {
    mockApi.operationsInbox.mockResolvedValue({
      ...busyInbox,
      items: [
        item({
          id: "source:account:7",
          kind: "source_overdue",
          title: "UOB Card: 9 days overdue",
          action: { label: "Upload", route: "/ingest", params: { account_id: "7" }, run: null, admin_only: false },
          source: {
            source_key: "account:7", kind: "card_statement", label: "UOB Card", platform: "UOB",
            last_data_date: "2026-09-30", cadence: "monthly", grace_days: 5, default_cadence: "monthly",
            default_grace_days: 5, overridden: false, due_date: "2026-11-04", status: "overdue", overdue: true, days_overdue: 4,
          },
        }),
      ],
    });
    renderPage();
    const link = await screen.findByRole("link", { name: "Upload" });
    expect(link.getAttribute("href")).toMatch(/^\/ingest\?account_id=7&as_of=2026-10-31/);
  });
});
