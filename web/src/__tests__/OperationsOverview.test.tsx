import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import OperationsOverview from "../routes/OperationsOverview";
import { api } from "../lib/api";
import type { DataHubSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    dataHubSummary: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

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
});
