import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import OperationsOverview from "../routes/OperationsOverview";
import { api } from "../lib/api";
import type { Account, DataHubSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    dataHubSummary: vi.fn(),
    accounts: vi.fn(),
    marketDataRefreshNow: vi.fn(),
    ibkrFlexImportNow: vi.fn(),
    cryptoRefreshNow: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const ibkrAccountFixture: Account = {
  id: 9,
  name: "IBKR",
  platform: "IBKR",
  account_type: "BROKER",
  currency: "USD",
};

const summaryFixture: DataHubSummary = {
  linked_accounts: 6,
  platform_count: 5,
  currency_count: 3,
  import_health: {
    pending_count: 0,
    last_import_platform: "DBS Multiplier",
    last_import_at: "2 days ago",
  },
  market_data: { fresh: 39, stale: 3 },
  connected_wallet_count: 3,
  connected_wallet_labels: ["Ledger", "Phantom", "MetaMask"],
  recent_activity: [
    { kind: "import", title: "Imported DBS Multiplier statement", meta: "42 transactions · 3 duplicates skipped", occurred_at: "2 days ago" },
    { kind: "market_data", title: "Refreshed SGX market data", meta: "3 stale quotes resolved", occurred_at: "6 hours ago" },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <OperationsOverview />
    </MemoryRouter>,
  );
}

describe("OperationsOverview (Data Hub Overview)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.accounts.mockResolvedValue([ibkrAccountFixture]);
  });

  it("renders live stat cards, quick actions, and recent activity", async () => {
    mockApi.dataHubSummary.mockResolvedValue(summaryFixture);
    renderPage();

    await waitFor(() => expect(screen.getByText("6")).toBeInTheDocument());

    expect(screen.getByText("Linked accounts")).toBeInTheDocument();
    expect(screen.getByText("Across 5 platforms · 3 currencies")).toBeInTheDocument();
    expect(screen.getByText("0 pending")).toBeInTheDocument();
    expect(screen.getByText("39 / 42 fresh")).toBeInTheDocument();
    expect(screen.getByText("3 connected")).toBeInTheDocument();

    expect(screen.getByText("Quick actions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Import Statements/ })).toHaveAttribute("href", "/ingest");
    expect(screen.getByRole("link", { name: /Add Crypto Wallets/ })).toHaveAttribute("href", "/crypto");

    expect(screen.getByText("Recent activity")).toBeInTheDocument();
    expect(screen.getByText("Imported DBS Multiplier statement")).toBeInTheDocument();
    expect(screen.getByText("Refreshed SGX market data")).toBeInTheDocument();
  });

  it("renders an empty state when there is no recent activity", async () => {
    mockApi.dataHubSummary.mockResolvedValue({ ...summaryFixture, recent_activity: [] });
    renderPage();

    await waitFor(() => expect(screen.getByText("No recent activity yet.")).toBeInTheDocument());
  });

  it("triggers price, IBKR, and crypto refreshes from the Refresh now section", async () => {
    mockApi.dataHubSummary.mockResolvedValue(summaryFixture);
    mockApi.marketDataRefreshNow.mockResolvedValue({ status: "completed", exchanges: [{}, {}] });
    mockApi.ibkrFlexImportNow.mockResolvedValue({ counts: { positions: 14, nav_snapshots: 2 } });
    mockApi.cryptoRefreshNow.mockResolvedValue({ status: "queued", wallets_refreshed: 4 });

    renderPage();

    expect(await screen.findByText("Refresh now")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh prices" }));
    await waitFor(() => expect(screen.getByText("Refreshed 2 exchanges.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Refresh IBKR" }));
    await waitFor(() => expect(screen.getByText("Imported 14 positions, 2 NAV snapshots.")).toBeInTheDocument());
    expect(mockApi.ibkrFlexImportNow).toHaveBeenCalledWith(9);

    fireEvent.click(screen.getByRole("button", { name: "Refresh crypto" }));
    await waitFor(() => expect(screen.getByText("Queued refresh for 4 wallets.")).toBeInTheDocument());
  });

  it("disables the IBKR refresh button when no IBKR account is linked", async () => {
    mockApi.dataHubSummary.mockResolvedValue(summaryFixture);
    mockApi.accounts.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText("Refresh now")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh IBKR" })).toBeDisabled();
  });
});
