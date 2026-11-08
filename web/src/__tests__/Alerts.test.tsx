import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Alerts from "../routes/Alerts";
import InboxBell from "../components/InboxBell";
import { api } from "../lib/api";
import type { InboxResponse } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

vi.mock("../lib/api", () => ({ api: { operationsInbox: vi.fn() } }));
const mockApi = vi.mocked(api, true);

const inbox: InboxResponse = {
  as_of: "2026-11-08",
  count: 3,
  items: [
    {
      id: "job:market_data", kind: "job_failing", severity: "high", title: "Quote refresh is failing",
      detail: "3 failed runs in a row", source: null,
      action: { label: "Refresh prices", route: null, params: {}, run: "refresh_prices", admin_only: true },
    },
    {
      id: "import:4", kind: "unknown_format", severity: "medium", title: "Synthetic Bank: file format not recognised",
      detail: "odd.csv", source: null,
      action: { label: "Fix format", route: "/ingest", params: { job: "4" }, run: null, admin_only: false },
    },
    {
      id: "unmapped", kind: "unmapped_transactions", severity: "low", title: "5 transactions without a category",
      detail: null, source: null,
      action: { label: "Map transactions", route: "/cash-flow/map-transactions", params: {}, run: null, admin_only: false },
    },
  ],
  all_good: [],
  recent_activity: [],
};

function renderWithBell(narrow = false) {
  return render(
    <MemoryRouter>
      <InboxBell narrow={narrow} />
      <Alerts />
    </MemoryRouter>,
  );
}

describe("Alerts and the header bell read one list (#317)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearApiCache();
  });

  it("bell count = inbox count = the Alerts list, from one request", async () => {
    mockApi.operationsInbox.mockResolvedValue(inbox);
    renderWithBell();
    const list = await screen.findByRole("list", { name: "Alerts" });
    const alerts = within(list).getAllByTestId("alert-item");
    expect(screen.getByTestId("inbox-bell-count")).toHaveTextContent(String(inbox.count));
    expect(alerts).toHaveLength(inbox.count);
    expect(screen.getByLabelText("3 items need you")).toBeInTheDocument();
    expect(mockApi.operationsInbox).toHaveBeenCalledTimes(1);
  });

  it("each alert links to its fix; a refresh opens the Data Hub", async () => {
    mockApi.operationsInbox.mockResolvedValue(inbox);
    renderWithBell();
    const list = await screen.findByRole("list", { name: "Alerts" });
    expect(within(list).getByRole("link", { name: "Fix format" })).toHaveAttribute("href", "/ingest?job=4");
    expect(within(list).getByRole("link", { name: "Map transactions" })).toHaveAttribute("href", "/cash-flow/map-transactions");
    expect(within(list).getByRole("link", { name: "Open the Data Hub" })).toHaveAttribute("href", "/operations");
  });

  it("nothing open: no count on the bell, and Alerts says so", async () => {
    mockApi.operationsInbox.mockResolvedValue({ ...inbox, count: 0, items: [] });
    renderWithBell();
    expect(await screen.findByText(/Nothing needs you. Everything is up to date./)).toBeInTheDocument();
    expect(screen.queryByTestId("inbox-bell-count")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Nothing needs you")).toBeInTheDocument();
  });

  it("on a phone the bell is a link to the Data Hub with the same count", async () => {
    mockApi.operationsInbox.mockResolvedValue(inbox);
    render(
      <MemoryRouter>
        <InboxBell narrow />
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: "3 items need you" });
    expect(link).toHaveAttribute("href", "/operations");
  });

  it("shows a load error", async () => {
    mockApi.operationsInbox.mockRejectedValue(new Error("Network error"));
    render(
      <MemoryRouter>
        <Alerts />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Couldn't load alerts/)).toBeInTheDocument();
  });
});
