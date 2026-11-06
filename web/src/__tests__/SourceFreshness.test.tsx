import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourceFreshnessStrip from "../components/SourceFreshnessStrip";
import SourceFreshnessTable from "../components/SourceFreshnessTable";
import { api } from "../lib/api";
import type { SourceFreshness, SourceFreshnessRow } from "../lib/api";
import { cadenceLabel, overdueSummary, statusLabel } from "../lib/sourceFreshness";
import { clearApiCache } from "../lib/useApiResource";

// #252: the Data Hub's source freshness table and the Overview's overdue line.
// Synthetic sources only.

vi.mock("../lib/api", () => ({
  api: {
    sourceFreshness: vi.fn(),
    setSourceFreshnessCadence: vi.fn(),
    resetSourceFreshnessCadence: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function row(source_key: string, label: string, extra: Partial<SourceFreshnessRow> = {}): SourceFreshnessRow {
  return {
    source_key,
    kind: "bank_statement",
    label,
    platform: "DBS",
    last_data_date: "2026-10-31",
    cadence: "monthly",
    grace_days: 10,
    default_cadence: "monthly",
    default_grace_days: 10,
    overridden: false,
    due_date: "2026-12-10",
    status: "on_time",
    overdue: false,
    days_overdue: null,
    ...extra,
  };
}

const OVERDUE_CARD = row("account:2", "Synthetic Card", {
  kind: "card_statement",
  last_data_date: "2026-08-15",
  due_date: "2026-09-25",
  status: "overdue",
  overdue: true,
  days_overdue: 42,
});
const NEVER_LOADED = row("account:3", "Synthetic Empty Bank", {
  platform: "DBS_VICKERS",
  kind: "broker_statement",
  last_data_date: null,
  due_date: null,
  status: "never_loaded",
  overdue: true,
});
const ON_TIME_BANK = row("account:1", "Synthetic Savings");
const FLEX = row("account:4", "Synthetic Flex", {
  kind: "ibkr_flex",
  platform: "IBKR",
  last_data_date: "2026-11-05",
  cadence: "weekdays",
  grace_days: 2,
  default_cadence: "weekdays",
  default_grace_days: 2,
  due_date: "2026-11-10",
});

function freshness(sources: SourceFreshnessRow[]): SourceFreshness {
  return {
    as_of: "2026-11-06",
    overdue_count: sources.filter((s) => s.overdue).length,
    cadences: ["daily", "weekdays", "weekly", "monthly", "quarterly", "off"],
    sources,
  };
}

function renderWithRouter(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("source freshness labels", () => {
  it("says the cadence with its grace in the right unit", () => {
    expect(cadenceLabel("monthly", 10)).toBe("Monthly · 10 days' grace");
    expect(cadenceLabel("weekdays", 1)).toBe("Weekdays · 1 weekday's grace");
    expect(cadenceLabel("daily", 0)).toBe("Daily");
    expect(cadenceLabel("off", 5)).toBe("Not tracked");
  });

  it("says how long a source is overdue", () => {
    expect(statusLabel(OVERDUE_CARD)).toBe("42 days overdue");
    expect(statusLabel({ ...OVERDUE_CARD, days_overdue: 1 })).toBe("1 day overdue");
    expect(statusLabel(NEVER_LOADED)).toBe("No data yet");
    expect(statusLabel(ON_TIME_BANK)).toBe("On time");
  });

  it("summarises overdue sources, at most three by name", () => {
    expect(overdueSummary(freshness([ON_TIME_BANK]))).toBeNull();
    expect(overdueSummary(undefined)).toBeNull();
    expect(overdueSummary(freshness([OVERDUE_CARD, NEVER_LOADED, ON_TIME_BANK]))).toBe(
      "2 sources overdue: Synthetic Card (42 days), Synthetic Empty Bank (no data yet)",
    );
    const many = [1, 2, 3, 4, 5].map((n) => row(`account:${n}`, `Card ${n}`, { status: "overdue", overdue: true, days_overdue: n }));
    expect(overdueSummary(freshness(many))).toBe(
      "5 sources overdue: Card 1 (1 day), Card 2 (2 days), Card 3 (3 days) and 2 more",
    );
  });
});

describe("<SourceFreshnessStrip>", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
  });

  it("shows one line with a link to the Data Hub when something is overdue", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([OVERDUE_CARD, ON_TIME_BANK]));
    renderWithRouter(<SourceFreshnessStrip />);
    const strip = await screen.findByTestId("source-freshness-strip");
    expect(strip).toHaveTextContent("1 source overdue: Synthetic Card (42 days)");
    expect(within(strip).getByRole("link", { name: /open data hub/i })).toHaveAttribute("href", "/operations");
  });

  it("renders nothing when every source is on time", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([ON_TIME_BANK, FLEX]));
    const { container } = renderWithRouter(<SourceFreshnessStrip />);
    await waitFor(() => expect(mockApi.sourceFreshness).toHaveBeenCalled());
    await Promise.resolve();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the load fails", async () => {
    mockApi.sourceFreshness.mockRejectedValue(new Error("boom"));
    const { container } = renderWithRouter(<SourceFreshnessStrip />);
    await waitFor(() => expect(mockApi.sourceFreshness).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("<SourceFreshnessTable>", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
  });

  it("lists each source with its last data, cadence and status", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([OVERDUE_CARD, NEVER_LOADED, ON_TIME_BANK, FLEX]));
    renderWithRouter(<SourceFreshnessTable />);
    const card = await screen.findByTestId("source-freshness-row-account:2");
    expect(within(card).getByText("Synthetic Card")).toBeInTheDocument();
    expect(within(card).getByText("Card statement · DBS")).toBeInTheDocument();
    expect(within(card).getByText("15 Aug 2026")).toBeInTheDocument();
    expect(within(card).getByText("Monthly · 10 days' grace")).toBeInTheDocument();
    expect(within(card).getByText("42 days overdue")).toBeInTheDocument();
    expect(within(card).getByText("Was due 25 Sep 2026")).toBeInTheDocument();

    const never = screen.getByTestId("source-freshness-row-account:3");
    expect(within(never).getByText("Never")).toBeInTheDocument();
    expect(within(never).getByText("No data yet")).toBeInTheDocument();
    expect(within(never).getByText("Broker statement · DBS Vickers")).toBeInTheDocument();

    const flex = screen.getByTestId("source-freshness-row-account:4");
    expect(within(flex).getByText("Weekdays · 2 weekdays' grace")).toBeInTheDocument();
    expect(within(flex).getByText("On time")).toBeInTheDocument();
    expect(within(flex).getByText("Next due by 10 Nov 2026")).toBeInTheDocument();

    expect(screen.getByText(/2 of 4 sources overdue/)).toBeInTheDocument();
  });

  it("saves a per-source cadence and reloads the table", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([OVERDUE_CARD]));
    mockApi.setSourceFreshnessCadence.mockResolvedValue({ ...OVERDUE_CARD, cadence: "quarterly", grace_days: 5, overridden: true });
    renderWithRouter(<SourceFreshnessTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Change expected cadence for Synthetic Card" }));

    const editor = screen.getByRole("group", { name: "Expected cadence for Synthetic Card" });
    fireEvent.change(within(editor).getByLabelText("Expected"), { target: { value: "quarterly" } });
    fireEvent.change(within(editor).getByLabelText("Grace (days)"), { target: { value: "5" } });
    mockApi.sourceFreshness.mockResolvedValue(
      freshness([{ ...OVERDUE_CARD, cadence: "quarterly", grace_days: 5, overridden: true, status: "on_time", overdue: false }]),
    );
    fireEvent.click(within(editor).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockApi.setSourceFreshnessCadence).toHaveBeenCalledWith("account:2", { cadence: "quarterly", grace_days: 5 }),
    );
    await screen.findByText("Your setting");
    expect(screen.getByText("Quarterly · 5 days' grace")).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(mockApi.sourceFreshness).toHaveBeenCalledTimes(2);
  });

  it("refuses a grace outside 0-90 and resets an override to the default", async () => {
    const overridden = { ...ON_TIME_BANK, cadence: "weekly", grace_days: 2, overridden: true };
    mockApi.sourceFreshness.mockResolvedValue(freshness([overridden]));
    mockApi.resetSourceFreshnessCadence.mockResolvedValue(ON_TIME_BANK);
    renderWithRouter(<SourceFreshnessTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Change expected cadence for Synthetic Savings" }));
    const editor = screen.getByRole("group");
    fireEvent.change(within(editor).getByLabelText("Grace (days)"), { target: { value: "200" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save" }));
    expect(await within(editor).findByRole("alert")).toHaveTextContent("0 to 90");
    expect(mockApi.setSourceFreshnessCadence).not.toHaveBeenCalled();

    fireEvent.click(within(editor).getByRole("button", { name: "Use default (Monthly · 10 days' grace)" }));
    await waitFor(() => expect(mockApi.resetSourceFreshnessCadence).toHaveBeenCalledWith("account:1"));
  });

  it("says so when there are no sources", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([]));
    renderWithRouter(<SourceFreshnessTable />);
    expect(await screen.findByText(/No data sources yet/)).toBeInTheDocument();
  });
});
