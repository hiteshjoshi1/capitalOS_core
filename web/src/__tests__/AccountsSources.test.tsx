import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AccountsSources from "../routes/AccountsSources";
import { api } from "../lib/api";
import type { Account, DataHubSummary, SourceFreshness, SourceFreshnessRow } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";
import { buildSourceRows, filterSourceRows, primaryAction } from "../lib/sources";

vi.mock("../lib/api", () => ({
  api: {
    sourceFreshness: vi.fn(),
    dataHubSummary: vi.fn(),
    accounts: vi.fn(),
    updateAccount: vi.fn(),
    ibkrFlexImportNow: vi.fn(),
    cryptoRefreshNow: vi.fn(),
    marketDataRefreshNow: vi.fn(),
    fxBackfill: vi.fn(),
    setSourceFreshnessCadence: vi.fn(),
    resetSourceFreshnessCadence: vi.fn(),
  },
}));

const authState = { user: { id: 1, username: "demo", is_admin: false } };
vi.mock("../context/useAuth", () => ({ useAuth: () => authState }));

const mockApi = vi.mocked(api, true);

function src(partial: Partial<SourceFreshnessRow> & Pick<SourceFreshnessRow, "source_key" | "kind" | "label">): SourceFreshnessRow {
  return {
    platform: null,
    last_data_date: "2026-11-03",
    cadence: "monthly",
    grace_days: 10,
    default_cadence: "monthly",
    default_grace_days: 10,
    overridden: false,
    due_date: "2026-12-13",
    status: "on_time",
    overdue: false,
    days_overdue: null,
    ...partial,
  };
}

const SOURCES: SourceFreshnessRow[] = [
  src({ source_key: "account:1", kind: "bank_statement", label: "Synthetic Savings", platform: "DBS" }),
  src({
    source_key: "account:2", kind: "card_statement", label: "Synthetic Card", platform: "DBS",
    last_data_date: "2026-10-02", status: "overdue", overdue: true, days_overdue: 5, due_date: "2026-11-03",
  }),
  src({ source_key: "account:3", kind: "ibkr_flex", label: "Synthetic Broker", platform: "IBKR", cadence: "weekdays", grace_days: 2 }),
  src({ source_key: "wallet:abc", kind: "crypto_wallet", label: "Phantom", platform: "solana", cadence: "daily", grace_days: 1 }),
  src({ source_key: "exchange:SGX", kind: "market_data", label: "SGX quotes", platform: "SGX", cadence: "weekdays", grace_days: 1 }),
  src({ source_key: "fx", kind: "fx", label: "FX rates", cadence: "weekdays", grace_days: 1 }),
  src({ source_key: "account:4", kind: "bank_statement", label: "Old Saver", platform: "CITI" }),
];

const ACCOUNTS: Account[] = [
  { id: 1, name: "Synthetic Savings", platform: "DBS", account_type: "BANK", currency: "SGD" },
  { id: 2, name: "Synthetic Card", platform: "DBS", account_type: "CREDIT_CARD", currency: "SGD" },
  { id: 3, name: "Synthetic Broker", platform: "IBKR", account_type: "BROKER", currency: "USD" },
  {
    id: 4, name: "Old Saver", platform: "CITI", account_type: "BANK", currency: "SGD",
    data_month: "2026-10", carried_forward_from: "2026-08-20",
  },
];

const UNPRICED: DataHubSummary["market_data"]["unpriced_holdings"] = [
  { symbol: "SGDMMF", name: "Money fund", currency: "SGD", exchange_code: "SGX", platform: "DBS", reason: "no_symbol" },
];

function renderPage() {
  mockApi.sourceFreshness.mockResolvedValue({ as_of: "2026-11-08", overdue_count: 1, cadences: [], sources: SOURCES } as SourceFreshness);
  mockApi.dataHubSummary.mockResolvedValue({ market_data: { unpriced_holdings: UNPRICED } } as unknown as DataHubSummary);
  mockApi.accounts.mockResolvedValue(ACCOUNTS);
  return render(
    <MemoryRouter>
      <AccountsSources />
    </MemoryRouter>,
  );
}

describe("Accounts & sources (#318)", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
    authState.user.is_admin = false;
  });

  it("lists every source with one action, what needs you first", async () => {
    renderPage();
    const card = await screen.findByTestId("source-row-account:2");
    const rows = screen.getAllByTestId(/^source-row-/);
    // The overdue card and the SGX feed with an unpriced holding come first.
    expect(rows.slice(0, 2).map((r) => r.getAttribute("data-testid")).sort()).toEqual([
      "source-row-account:2",
      "source-row-exchange:SGX",
    ]);
    expect(within(card).getByText("5 days overdue")).toBeInTheDocument();
    // Upload opens the prefilled upload (#278).
    expect(within(card).getByRole("link", { name: "Upload" }).getAttribute("href")).toMatch(/^\/ingest\?account_id=2/);
    expect(within(screen.getByTestId("source-row-exchange:SGX")).getByRole("link", { name: "Fix 1" })).toHaveAttribute(
      "href",
      "/market-data",
    );
    expect(screen.getByText("2 need you · 5 up to date.")).toBeInTheDocument();
  });

  it("refreshes IBKR and wallets; shared feeds say an admin refreshes them", async () => {
    mockApi.ibkrFlexImportNow.mockResolvedValue({ counts: { positions: 12 } });
    mockApi.cryptoRefreshNow.mockResolvedValue({});
    renderPage();
    const broker = await screen.findByTestId("source-row-account:3");
    fireEvent.click(within(broker).getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mockApi.ibkrFlexImportNow).toHaveBeenCalledWith(3));
    expect(await within(broker).findByText("Imported 12 positions.")).toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId("source-row-wallet:abc")).getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mockApi.cryptoRefreshNow).toHaveBeenCalled());

    expect(within(screen.getByTestId("source-row-fx")).getByText("Admin refreshes this")).toBeInTheDocument();
    expect(within(screen.getByTestId("source-row-fx")).queryByRole("button", { name: "Fetch past" })).not.toBeInTheDocument();
  });

  it("filters by type and searches by name", async () => {
    renderPage();
    await screen.findByTestId("source-row-account:1");
    await userEvent.click(screen.getByRole("button", { name: "Cards" }));
    expect(screen.getAllByTestId(/^source-row-/).map((r) => r.getAttribute("data-testid"))).toEqual(["source-row-account:2"]);
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search sources" }), "phantom");
    expect(screen.getAllByTestId(/^source-row-/).map((r) => r.getAttribute("data-testid"))).toEqual(["source-row-wallet:abc"]);
  });

  it("closes an account from ⋯ and shows it as closed (#207)", async () => {
    renderPage();
    const row = await screen.findByTestId("source-row-account:1");
    fireEvent.click(within(row).getByRole("button", { name: "Close account…" }));
    fireEvent.click(within(row).getByRole("button", { name: "Close Synthetic Savings" }));
    const date = within(row).getByLabelText("Close date for Synthetic Savings");
    fireEvent.change(date, { target: { value: "2026-11-01" } });
    mockApi.updateAccount.mockResolvedValueOnce({ ...ACCOUNTS[0], closed_on: "2026-11-01" });
    mockApi.accounts.mockResolvedValue([{ ...ACCOUNTS[0], closed_on: "2026-11-01" }, ...ACCOUNTS.slice(1)]);
    fireEvent.click(within(row).getByRole("button", { name: "Close account" }));
    await waitFor(() => expect(mockApi.updateAccount).toHaveBeenCalledWith(1, { closed_on: "2026-11-01" }));
    expect(await screen.findByText("Closed 1 Nov 2026")).toBeInTheDocument();
    // A closed account has no primary action.
    expect(within(screen.getByTestId("source-row-account:1")).queryByRole("link", { name: "Upload" })).not.toBeInTheDocument();
  });

  it("flags a carried-forward account and opens the cadence editor from ⋯", async () => {
    renderPage();
    const row = await screen.findByTestId("source-row-account:4");
    expect(within(row).getByText(/2026-10 shows data from 2026-08-20 \(carried forward\)/)).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: /Expected: Monthly/ }));
    expect(within(row).getByRole("group", { name: "Expected cadence for Old Saver" })).toBeInTheDocument();
  });
});

describe("source rows (#318)", () => {
  it("chooses one action per kind", () => {
    const today = "2026-11-08";
    expect(primaryAction(SOURCES[0], { closed: false, unpriced: 0, today })).toMatchObject({ kind: "link", label: "Upload" });
    expect(primaryAction(SOURCES[2], { closed: false, unpriced: 0, today })).toMatchObject({ run: "refresh_ibkr", accountId: 3 });
    expect(primaryAction(SOURCES[4], { closed: false, unpriced: 2, today })).toMatchObject({ kind: "link", label: "Fix 2" });
    expect(primaryAction(SOURCES[4], { closed: false, unpriced: 0, today })).toMatchObject({ run: "refresh_prices", adminOnly: true });
    expect(primaryAction(SOURCES[5], { closed: false, unpriced: 0, today })).toMatchObject({ run: "fx_backfill", adminOnly: true });
    expect(primaryAction(SOURCES[0], { closed: true, unpriced: 0, today })).toBeNull();
  });

  it("types rows and filters them", () => {
    const rows = buildSourceRows(SOURCES, ACCOUNTS, [], "2026-11-08");
    expect(rows.find((r) => r.key === "account:3")?.type).toBe("broker");
    expect(rows.find((r) => r.key === "fx")?.type).toBe("feed");
    expect(filterSourceRows(rows, "feed", "").map((r) => r.key).sort()).toEqual(["exchange:SGX", "fx"]);
    expect(filterSourceRows(rows, "all", "dbs card").map((r) => r.key)).toEqual(["account:2"]);
  });
});
