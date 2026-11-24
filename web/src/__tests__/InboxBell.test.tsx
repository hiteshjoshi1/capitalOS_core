import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import InboxBell from "../components/InboxBell";
import RedirectKeepingSearch from "../components/RedirectKeepingSearch";
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

function renderBell(narrow = false) {
  return render(
    <MemoryRouter>
      <InboxBell narrow={narrow} />
    </MemoryRouter>,
  );
}

function Where() {
  const { pathname, search } = useLocation();
  return <div data-testid="where">{`${pathname}${search}`}</div>;
}

describe("the header bell reads the Data Hub inbox (#317)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearApiCache();
  });

  it("bell count = inbox count = the bell's list, from one request", async () => {
    mockApi.operationsInbox.mockResolvedValue(inbox);
    renderBell();
    const panel = await screen.findByRole("group", { name: "Needs you" });
    await within(panel).findByText("Quote refresh is failing");
    expect(screen.getByTestId("inbox-bell-count")).toHaveTextContent(String(inbox.count));
    expect(within(panel).getAllByRole("listitem")).toHaveLength(inbox.count);
    expect(screen.getByLabelText("3 items need you")).toBeInTheDocument();
    expect(mockApi.operationsInbox).toHaveBeenCalledTimes(1);
  });

  it("each item links to its fix; a refresh opens the Data Hub", async () => {
    mockApi.operationsInbox.mockResolvedValue(inbox);
    renderBell();
    const panel = await screen.findByRole("group", { name: "Needs you" });
    expect(await within(panel).findByRole("link", { name: /Synthetic Bank: file format not recognised/ })).toHaveAttribute("href", "/ingest?job=4");
    expect(within(panel).getByRole("link", { name: /5 transactions without a category/ })).toHaveAttribute("href", "/cash-flow/map-transactions");
    expect(within(panel).getByRole("link", { name: /Quote refresh is failing/ })).toHaveAttribute("href", "/operations");
  });

  it("nothing open: no count on the bell, and it says so", async () => {
    mockApi.operationsInbox.mockResolvedValue({ ...inbox, count: 0, items: [] });
    renderBell();
    expect(await screen.findByText(/Nothing needs you\./)).toBeInTheDocument();
    expect(screen.queryByTestId("inbox-bell-count")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Nothing needs you")).toBeInTheDocument();
  });

  it("on a phone the bell is a link to the Data Hub with the same count", async () => {
    mockApi.operationsInbox.mockResolvedValue(inbox);
    renderBell(true);
    const link = await screen.findByRole("link", { name: "3 items need you" });
    expect(link).toHaveAttribute("href", "/operations");
  });
});

describe("/alerts (#475, V3)", () => {
  it("opens the Data Hub Inbox, keeping the query string: the Alerts page is gone", () => {
    render(
      <MemoryRouter initialEntries={["/alerts?month=2026-11"]}>
        <Routes>
          <Route path="/alerts" element={<RedirectKeepingSearch to="/operations" />} />
          <Route path="/operations" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/operations?month=2026-11");
  });
});
