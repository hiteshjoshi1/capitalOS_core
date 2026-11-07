import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourceFreshnessStrip from "../components/SourceFreshnessStrip";
import SourceFreshnessTable from "../components/SourceFreshnessTable";
import { api } from "../lib/api";
import type { SourceFreshness, SourceFreshnessRow } from "../lib/api";
import {
  expectedStatementDate,
  isIsoDate,
  sourceLink,
  uploadExpectationLine,
} from "../lib/sourceFreshness";
import { clearApiCache } from "../lib/useApiResource";

// #278: an upload source's freshness row opens Upload prefilled. Synthetic sources only.

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
    kind: "card_statement",
    label,
    platform: "DBS",
    last_data_date: "2026-09-30",
    cadence: "monthly",
    grace_days: 10,
    default_cadence: "monthly",
    default_grace_days: 10,
    overridden: false,
    due_date: "2026-11-09",
    status: "overdue",
    overdue: true,
    days_overdue: 3,
    ...extra,
  };
}

function freshness(sources: SourceFreshnessRow[]): SourceFreshness {
  return {
    as_of: "2026-11-12",
    overdue_count: sources.filter((s) => s.overdue).length,
    cadences: ["daily", "weekdays", "weekly", "monthly", "quarterly", "off"],
    sources,
  };
}

const TODAY = "2026-11-12";

describe("expectedStatementDate", () => {
  it("is one period after the last data, per cadence", () => {
    expect(expectedStatementDate("2026-11-05", "daily", TODAY)).toBe("2026-11-06");
    // Friday → Monday
    expect(expectedStatementDate("2026-11-06", "weekdays", TODAY)).toBe("2026-11-09");
    expect(expectedStatementDate("2026-11-02", "weekly", TODAY)).toBe("2026-11-09");
    expect(expectedStatementDate("2026-09-15", "monthly", TODAY)).toBe("2026-10-15");
    expect(expectedStatementDate("2026-06-15", "quarterly", TODAY)).toBe("2026-09-15");
  });

  it("keeps a month-end a month-end, and clamps other days to the month", () => {
    expect(expectedStatementDate("2026-09-30", "monthly", TODAY)).toBe("2026-10-31");
    expect(expectedStatementDate("2026-01-31", "monthly", TODAY)).toBe("2026-02-28");
    expect(expectedStatementDate("2026-01-30", "monthly", TODAY)).toBe("2026-02-28");
    expect(expectedStatementDate("2026-06-30", "quarterly", TODAY)).toBe("2026-09-30");
    expect(expectedStatementDate("2025-12-31", "monthly", "2026-03-01")).toBe("2026-01-31");
  });

  it("is never later than today", () => {
    expect(expectedStatementDate("2026-10-31", "monthly", TODAY)).toBe(TODAY);
    expect(expectedStatementDate("2026-11-12", "daily", TODAY)).toBe(TODAY);
    expect(expectedStatementDate("2026-09-30", "quarterly", TODAY)).toBe(TODAY);
  });

  it("is today with no data yet, and nothing for an untracked source", () => {
    expect(expectedStatementDate(null, "monthly", TODAY)).toBe(TODAY);
    expect(expectedStatementDate("garbage", "monthly", TODAY)).toBe(TODAY);
    expect(expectedStatementDate("2026-09-30", "off", TODAY)).toBeNull();
  });

  it("validates calendar dates", () => {
    expect(isIsoDate("2026-02-28")).toBe(true);
    expect(isIsoDate("2026-02-30")).toBe(false);
    expect(isIsoDate("2026-2-3")).toBe(false);
    expect(isIsoDate(null)).toBe(false);
  });
});

describe("sourceLink", () => {
  it("opens Upload for each upload kind, prefilled", () => {
    for (const kind of ["broker_statement", "bank_statement", "card_statement", "account_statement"]) {
      const link = sourceLink(row("account:7", "Synthetic", { kind }), TODAY);
      const url = new URL(link ?? "", "http://x");
      expect(url.pathname).toBe("/ingest");
      expect(url.searchParams.get("account_id")).toBe("7");
      expect(url.searchParams.get("as_of")).toBe("2026-10-31");
      expect(url.searchParams.get("last_data")).toBe("2026-09-30");
      expect(url.searchParams.get("cadence")).toBe("monthly");
    }
  });

  it("leaves out the date for a never-loaded or untracked source's missing parts", () => {
    const never = new URL(sourceLink(row("account:7", "S", { last_data_date: null }), TODAY) ?? "", "http://x");
    expect(never.searchParams.get("as_of")).toBe(TODAY);
    expect(never.searchParams.has("last_data")).toBe(false);
    const off = new URL(sourceLink(row("account:7", "S", { cadence: "off" }), TODAY) ?? "", "http://x");
    expect(off.searchParams.has("as_of")).toBe(false);
  });

  it("sends the quote feed to Market data and never links Flex, wallets or FX to Upload", () => {
    expect(sourceLink(row("exchange:SGX", "SGX quotes", { kind: "market_data" }), TODAY)).toBe("/market-data");
    expect(sourceLink(row("account:4", "Flex", { kind: "ibkr_flex" }), TODAY)).toBeNull();
    expect(sourceLink(row("wallet:2", "Wallet", { kind: "crypto_wallet" }), TODAY)).toBeNull();
    expect(sourceLink(row("fx", "FX rates", { kind: "fx" }), TODAY)).toBeNull();
  });
});

describe("uploadExpectationLine", () => {
  it("names the period that's due and the last data", () => {
    expect(uploadExpectationLine("Synthetic Card", "2026-10-31", "2026-09-30", "monthly", "2026-11-07")).toBe(
      "Synthetic Card: statement due for October 2026 (last data 30 Sep 2026)",
    );
    expect(uploadExpectationLine("Synthetic Card", "2026-11-06", "2026-11-05", "daily", "2026-11-07")).toBe(
      "Synthetic Card: statement due for 6 Nov 2026 (last data 5 Nov 2026)",
    );
    expect(uploadExpectationLine("Synthetic Card", TODAY, null, "monthly")).toBe(
      "Synthetic Card: no data yet. Upload its newest statement.",
    );
  });

  it("says up to date, never due, while the next period hasn't ended", () => {
    // On time: October's statement is in, November's isn't due until 30 Nov.
    expect(uploadExpectationLine("Synthetic Card", "2026-11-07", "2026-10-31", "monthly", "2026-11-07")).toBe(
      "Synthetic Card: up to date (last data 31 Oct 2026). The next statement covers November 2026.",
    );
    // The period ends today: due.
    expect(uploadExpectationLine("Synthetic Card", "2026-11-30", "2026-10-31", "monthly", "2026-11-30")).toBe(
      "Synthetic Card: statement due for November 2026 (last data 31 Oct 2026)",
    );
  });
});

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderAt(node: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={["/operations"]}>
      <Routes>
        <Route path="/operations" element={node} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("<SourceFreshnessTable> links (#278)", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
  });

  it("opens prefilled Upload from an upload row (name link and the row itself)", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([row("account:2", "Synthetic Card")]));
    renderAt(<SourceFreshnessTable />);
    const link = await screen.findByRole("link", { name: "Upload a statement for Synthetic Card" });
    expect(link.getAttribute("href")).toMatch(/^\/ingest\?account_id=2&as_of=\d{4}-\d{2}-\d{2}&last_data=2026-09-30&cadence=monthly$/);
    fireEvent.click(screen.getByTestId("source-freshness-row-account:2").querySelector("td:nth-child(2)")!);
    expect(screen.getByTestId("where").textContent).toMatch(/^\/ingest\?account_id=2&/);
  });

  it("doesn't navigate when the row's own Change button is used", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([row("account:2", "Synthetic Card")]));
    renderAt(<SourceFreshnessTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Change expected cadence for Synthetic Card" }));
    expect(screen.queryByTestId("where")).toBeNull();
    expect(screen.getByRole("group", { name: "Expected cadence for Synthetic Card" })).toBeInTheDocument();
  });

  it("makes no link of Flex, wallet or FX rows", async () => {
    mockApi.sourceFreshness.mockResolvedValue(
      freshness([
        row("account:4", "Synthetic Flex", { kind: "ibkr_flex" }),
        row("wallet:1", "Synthetic Wallet", { kind: "crypto_wallet" }),
        row("fx", "FX rates", { kind: "fx" }),
      ]),
    );
    renderAt(<SourceFreshnessTable />);
    await screen.findByText("Synthetic Flex");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    fireEvent.click(screen.getByText("Synthetic Flex"));
    expect(screen.queryByTestId("where")).toBeNull();
  });
});

describe("<SourceFreshnessStrip> upload link (#278)", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
  });

  it("links straight to Upload when the only overdue source is an upload", async () => {
    mockApi.sourceFreshness.mockResolvedValue(freshness([row("account:2", "Synthetic Card")]));
    renderAt(<SourceFreshnessStrip />);
    const link = await screen.findByRole("link", { name: "Upload it →" });
    expect(link.getAttribute("href")).toMatch(/^\/ingest\?account_id=2&/);
    expect(screen.getByRole("link", { name: "Open Data Hub →" })).toBeInTheDocument();
  });

  it("only links the Data Hub when more than one source is overdue", async () => {
    mockApi.sourceFreshness.mockResolvedValue(
      freshness([row("account:2", "Synthetic Card"), row("account:3", "Synthetic Bank", { kind: "bank_statement" })]),
    );
    renderAt(<SourceFreshnessStrip />);
    await screen.findByRole("link", { name: "Open Data Hub →" });
    expect(screen.queryByRole("link", { name: "Upload it →" })).toBeNull();
  });
});
