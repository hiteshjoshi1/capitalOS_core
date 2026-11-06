import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TrendBarChart from "../components/TrendBarChart";
import ValueTrendChart from "../components/ValueTrendChart";
import { monthEndCloseDate } from "../lib/selectedMonth";

// #241 (D-61): the open month's bar is live, month to date, and labelled so.
describe("six-month trends: the open month is month to date", () => {
  it("TrendBarChart labels the live bar MTD and says so to screen readers", () => {
    const { container } = render(
      <TrendBarChart
        ariaLabel="Six-month cash trend"
        points={[
          { month: "2026-09", value: 100, displayValue: "S$ 100" },
          { month: "2026-10", value: 120, displayValue: "S$ 120" },
          { month: "2026-11", value: 130, displayValue: "S$ 130", isLive: true },
        ]}
      />,
    );
    expect(screen.getByText("Oct '26")).toBeInTheDocument();
    expect(screen.getByText("MTD")).toBeInTheDocument();
    expect(screen.queryByText("Nov '26")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".trendBarFill.live")).toHaveLength(1);
    expect(screen.getByRole("img", { name: "Six-month cash trend" })).toHaveAccessibleDescription(
      expect.stringContaining("Nov '26 (month to date, live)"),
    );
  });

  it("ValueTrendChart labels the live bar MTD, in the bars and the data strip", () => {
    const { container } = render(
      <ValueTrendChart
        ariaLabel="Six-month stock trend"
        points={[
          { month: "2026-10", value: 500, is_live: false },
          { month: "2026-11", value: 550, is_live: true },
        ]}
        formatMoney={(value) => `S$ ${value}`}
        formatCompactMoney={(value) => `S$ ${value}`}
      />,
    );
    expect(screen.getAllByText("MTD")).toHaveLength(2);
    expect(screen.getAllByText("Oct '26")).toHaveLength(2);
    expect(container.querySelectorAll(".valueTrendBar.live")).toHaveLength(1);
    expect(container.querySelector(".valueTrendBar.live")?.getAttribute("title")).toBe(
      "Nov '26 (month to date, live): S$ 550",
    );
  });

  it("charts without a live bar are unchanged", () => {
    const { container } = render(
      <TrendBarChart ariaLabel="12-month dividend income" points={[{ month: "2026-10", value: 5, displayValue: "5" }]} />,
    );
    expect(screen.getByText("Oct '26")).toBeInTheDocument();
    expect(screen.queryByText("MTD")).not.toBeInTheDocument();
    expect(container.querySelector(".live")).toBeNull();
  });
});

describe("monthEndCloseDate", () => {
  it("is the day before the month-end anchor date", () => {
    expect(monthEndCloseDate("2026-11-01T00:00:00+00:00")).toBe("2026-10-31");
    expect(monthEndCloseDate("2026-03-01T00:00:00+00:00")).toBe("2026-02-28");
    expect(monthEndCloseDate("2026-01-05T00:00:00+00:00")).toBe("2026-01-04");
    expect(monthEndCloseDate("2026-01-01")).toBe("2025-12-31");
  });

  it("is null without a boundary", () => {
    expect(monthEndCloseDate(null)).toBeNull();
    expect(monthEndCloseDate(undefined)).toBeNull();
    expect(monthEndCloseDate("soon")).toBeNull();
  });
});
