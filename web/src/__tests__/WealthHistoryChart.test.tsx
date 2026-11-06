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
  uploads: [],
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
    expect(getByText("Click or press Enter to inspect this month →")).toBeInTheDocument();

    fireEvent.click(host);
    expect(onSelectMonth).toHaveBeenCalledWith("2026-05");

    vi.restoreAllMocks();
  });

  it("puts the still-open month's uploads on the 'now' marker", () => {
    const svgRectMock = { left: 0, top: 0, width: 900, height: 320, right: 900, bottom: 320, x: 0, y: 0, toJSON: () => ({}) };
    vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockReturnValue(svgRectMock as DOMRect);

    const points = [point({ month: "2026-06", anchor_date: "2026-07-01" })];
    const { container, getByText } = render(
      <WealthHistoryChart
        points={points}
        now={{ ...now, uploads: ["OCBC"] }}
        mode="total"
        formatMoney={formatMoney}
        formatMoneyShort={formatMoneyShort}
      />,
    );

    expect(container.querySelectorAll(".whUploadMark")).toHaveLength(1);
    // One point + the "now" slot over width 900: "now" sits at x ~ 675.
    fireEvent.pointerMove(container.querySelector(".whChartSvgHost")!, { clientX: 675, clientY: 100 });
    expect(getByText("Now (live prices)")).toBeInTheDocument();
    expect(getByText(/Uploaded this month:/)).toBeInTheDocument();

    vi.restoreAllMocks();
  });
});

// #151: the drill-down works from the keyboard.
describe("WealthHistoryChart keyboard drill-down", () => {
  const points = [
    point({ month: "2026-04", total: 800 }),
    point({ month: "2026-05", total: 900 }),
    point({ month: "2026-06", total: 1000 }),
  ];

  it("is one tab stop; arrows move between months, announced; Enter inspects", () => {
    const onSelectMonth = vi.fn();
    const { getByRole, container } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} onSelectMonth={onSelectMonth} />,
    );
    const host = getByRole("group", { name: /Net worth by month/ });
    expect(host).toHaveAttribute("tabindex", "0");
    const live = container.querySelector("[aria-live=polite]")!;

    fireEvent.focus(host);
    expect(live.textContent).toContain("June 2026: total S$ 1,000");
    fireEvent.keyDown(host, { key: "ArrowLeft" });
    expect(live.textContent).toContain("May 2026: total S$ 900");
    fireEvent.keyDown(host, { key: "Enter" });
    expect(onSelectMonth).toHaveBeenCalledWith("2026-05");

    fireEvent.keyDown(host, { key: "Home" });
    fireEvent.keyDown(host, { key: " " });
    expect(onSelectMonth).toHaveBeenLastCalledWith("2026-04");

    // End is the live "now" marker: announced, but not a month to inspect.
    fireEvent.keyDown(host, { key: "End" });
    expect(live.textContent).toContain("Now, live prices");
    fireEvent.keyDown(host, { key: "Enter" });
    expect(onSelectMonth).toHaveBeenCalledTimes(2);

    fireEvent.keyDown(host, { key: "Escape" });
    expect(live.textContent).toBe("");
  });

  it("marks the selected month (#223): its point, or 'now' for the open month", () => {
    const { getByTestId, getByText, rerender, queryByTestId } = render(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} selectedMonth="2026-05" />,
    );
    expect(getByTestId("wh-selected-month")).toHaveTextContent("Selected month: May 2026");
    expect(getByText("May '26")).toHaveClass("whAxisLabelSelected");

    rerender(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} selectedMonth="2999-01" />,
    );
    expect(getByTestId("wh-selected-month")).toHaveTextContent("Selected month: now");
    expect(getByText("now")).toHaveClass("whAxisLabelSelected");

    // Older than the range: nothing to mark.
    rerender(
      <WealthHistoryChart points={points} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} selectedMonth="2020-01" />,
    );
    expect(queryByTestId("wh-selected-month")).not.toBeInTheDocument();
  });

  it("always names the selected month on a long, thinned-out axis", () => {
    const many = Array.from({ length: 24 }, (_, i) => {
      const month = `20${24 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`;
      return point({ month, total: 1000 + i });
    });
    const { getByText } = render(
      <WealthHistoryChart points={many} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} selectedMonth="2024-02" />,
    );
    // 24 months show every third label; Feb '24 (index 1) is not one of them, but is selected.
    expect(getByText("Feb '24")).toHaveClass("whAxisLabelSelected");
  });

  it("an empty chart is not a tab stop", () => {
    const { getByRole } = render(
      <WealthHistoryChart points={[]} now={now} mode="total" formatMoney={formatMoney} formatMoneyShort={formatMoneyShort} />,
    );
    expect(getByRole("group")).not.toHaveAttribute("tabindex");
  });
});
