import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import WealthAttributionStrip from "../components/WealthAttributionStrip";
import type { WealthTimelinePoint } from "../lib/api";

function point(overrides: Partial<WealthTimelinePoint> = {}): WealthTimelinePoint {
  return {
    month: "2026-06",
    anchor_date: "2026-06-01",
    total: 1000,
    cash: 300,
    stocks_funds: 600,
    crypto: 100,
    liabilities: 0,
    source_freshness: [],
    freshness_status: "fresh",
    computed_at: "2026-06-01T00:00:00+00:00",
    uploads: [],
    ...overrides,
  };
}

const formatMoney = (value?: number | null) => (value == null ? "—" : `S$ ${value.toLocaleString()}`);

describe("WealthAttributionStrip", () => {
  it("renders one column per month that has a component delta (skips the first/start-of-history month)", () => {
    const points = [
      point({ month: "2026-04", total: 900, cash: 300, stocks_funds: 500, crypto: 100 }),
      point({ month: "2026-05", total: 950, cash: 310, stocks_funds: 540, crypto: 100 }),
      point({ month: "2026-06", total: 1000, cash: 300, stocks_funds: 600, crypto: 100 }),
    ];
    const { container } = render(
      <WealthAttributionStrip points={points} formatMoney={formatMoney} selectedMonth={null} onSelectMonth={vi.fn()} />,
    );
    // 3 points, but only points with a prior point get component deltas -> 2 columns.
    expect(container.querySelectorAll(".whAttribCol")).toHaveLength(2);
  });

  it("skips the gap month itself, but still renders a column for the next observed month (compared to the last observed point)", () => {
    const points = [
      point({ month: "2026-04" }),
      point({ month: "2026-05", total: 0, cash: 0, stocks_funds: 0, crypto: 0 }), // gap
      point({ month: "2026-06" }),
    ];
    const { container } = render(
      <WealthAttributionStrip points={points} formatMoney={formatMoney} selectedMonth={null} onSelectMonth={vi.fn()} />,
    );
    // Only 2026-06 gets a column — it has a comparable prior point (2026-04, skipping the gap).
    expect(container.querySelectorAll(".whAttribCol")).toHaveLength(1);
  });

  it("marks the selected month's column with the selected class", () => {
    const points = [
      point({ month: "2026-05", total: 900 }),
      point({ month: "2026-06", total: 1000 }),
    ];
    const { container } = render(
      <WealthAttributionStrip points={points} formatMoney={formatMoney} selectedMonth="2026-06" onSelectMonth={vi.fn()} />,
    );
    const selected = container.querySelector(".whAttribColSelected");
    expect(selected).not.toBeNull();
  });

  it("calls onSelectMonth with the clicked column's month", () => {
    const points = [
      point({ month: "2026-05", total: 900 }),
      point({ month: "2026-06", total: 1000 }),
    ];
    const onSelectMonth = vi.fn();
    const { container } = render(
      <WealthAttributionStrip points={points} formatMoney={formatMoney} selectedMonth={null} onSelectMonth={onSelectMonth} />,
    );
    const columns = container.querySelectorAll(".whAttribCol");
    fireEvent.click(columns[columns.length - 1]);
    expect(onSelectMonth).toHaveBeenCalledWith("2026-06");
  });

  it("shows a tooltip with the per-component delta on hover", () => {
    const points = [
      point({ month: "2026-05", total: 900, cash: 300, stocks_funds: 500, crypto: 100 }),
      point({ month: "2026-06", total: 1000, cash: 310, stocks_funds: 590, crypto: 100 }),
    ];
    const { container, getByText } = render(
      <WealthAttributionStrip points={points} formatMoney={formatMoney} selectedMonth={null} onSelectMonth={vi.fn()} />,
    );
    const columns = container.querySelectorAll(".whAttribCol");
    fireEvent.pointerEnter(columns[columns.length - 1]);
    expect(getByText(/Jun 26 Δ vs May 26/)).toBeInTheDocument();
    expect(getByText("S$ 90")).toBeInTheDocument(); // stocks_funds delta
    expect(getByText("S$ 10")).toBeInTheDocument(); // cash delta
  });
});
