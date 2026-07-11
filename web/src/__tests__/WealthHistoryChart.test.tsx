import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import WealthHistoryChart from "../components/WealthHistoryChart";
import type { WealthTimeline, WealthTimelinePoint } from "../lib/api";

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

const now: WealthTimeline["now"] = {
  total: 1000,
  cash: 300,
  stocks_funds: 600,
  crypto: 100,
  liabilities: 0,
  as_of: "2026-06-20T00:00:00+00:00",
};

const formatMoney = (value?: number | null) => (value == null ? "—" : `S$ ${value.toLocaleString()}`);
const formatMoneyShort = (value?: number | null) => (value == null ? "—" : `S$${Math.round(value)}`);

describe("WealthHistoryChart", () => {
  it("renders the chart svg, a grid, and the 'now' marker label", () => {
    const points = [point({ month: "2026-05", total: 900 }), point({ month: "2026-06", total: 1000 })];
    const { getByRole, getByText } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    expect(getByRole("img", { name: "Net worth over time" })).toBeInTheDocument();
    expect(getByText("now")).toBeInTheDocument();
  });

  it("shows the honesty legend but the component legend only in 'comp' mode", () => {
    const points = [point({ month: "2026-06" })];
    const { container, rerender } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    expect(container.querySelector(".whSeriesLegend")).not.toBeInTheDocument();
    expect(container.querySelector(".whHonestyLegend")).toBeInTheDocument();

    rerender(
      <WealthHistoryChart points={points} now={now} mode="comp" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    const legendItems = container.querySelectorAll(".whSeriesLegend .whSeriesLegendItem");
    expect(Array.from(legendItems).map((el) => el.textContent)).toEqual(["Stocks & funds", "Cash", "Crypto"]);
  });

  it("renders an upload marker with a title listing the uploaded platforms", () => {
    const points = [point({ month: "2026-06", uploads: ["dbs", "ocbc"] })];
    const { container } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    const marker = container.querySelector(".whUploadMark");
    expect(marker).not.toBeNull();
    expect(marker?.querySelector("title")?.textContent).toContain("Upload:");
  });

  it("does not render an upload marker for a month with no uploads", () => {
    const points = [point({ month: "2026-06", uploads: [] })];
    const { container } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    expect(container.querySelector(".whUploadMark")).toBeNull();
  });

  it("renders an outlier badge for a sharply-moving month and invokes onSelectMonth when clicked", () => {
    const points = [
      point({ month: "2026-01", total: 100 }),
      point({ month: "2026-02", total: 110 }),
      point({ month: "2026-03", total: 124 }),
      point({ month: "2026-04", total: 132 }),
      point({ month: "2026-05", total: 502 }), // sharp outlier jump
    ];
    const onSelectMonth = vi.fn();
    const { container } = render(
      <WealthHistoryChart
        points={points}
        now={{ ...now, total: 502 }}
        mode="total"
        formatMoney={formatMoney}
        formatMoneyShort={formatMoneyShort}
        onSelectMonth={onSelectMonth}
      />,
    );
    const badge = container.querySelector(".whOutlierBadge");
    expect(badge).not.toBeNull();
    fireEvent.click(badge!);
    expect(onSelectMonth).toHaveBeenCalledWith("2026-05");
  });

  it("draws dashed, lower-opacity segments between carried (non-fresh) points", () => {
    const points = [
      point({ month: "2026-05", total: 900, freshness_status: "carried" }),
      point({ month: "2026-06", total: 1000, freshness_status: "carried" }),
    ];
    const { container } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    const dashed = container.querySelector('line[stroke-dasharray="5 5"]');
    expect(dashed).not.toBeNull();
  });

  it("shows a hover tooltip with per-component values and a click hint when a point is hovered", () => {
    const svgRectMock = { left: 0, top: 0, width: 900, height: 320, right: 900, bottom: 320, x: 0, y: 0, toJSON: () => ({}) };
    vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockReturnValue(svgRectMock as DOMRect);

    const points = [point({ month: "2026-05", total: 900 }), point({ month: "2026-06", total: 1000 })];
    const onSelectMonth = vi.fn();
    const { container, getByText } = render(
      <WealthHistoryChart
        points={points}
        now={now}
        mode="total"
        formatMoney={formatMoney}
        formatMoneyShort={formatMoneyShort}
        onSelectMonth={onSelectMonth}
      />,
    );

    const host = container.querySelector(".whChartSvgHost")!;
    // Two points + a "now" slot spread over width 900 — hover near the first point (x ~ 205).
    fireEvent.pointerMove(host, { clientX: 205, clientY: 100 });

    expect(getByText("Total")).toBeInTheDocument();
    expect(getByText("Click to inspect this month →")).toBeInTheDocument();

    fireEvent.click(host);
    expect(onSelectMonth).toHaveBeenCalledWith("2026-05");

    vi.restoreAllMocks();
  });
});
