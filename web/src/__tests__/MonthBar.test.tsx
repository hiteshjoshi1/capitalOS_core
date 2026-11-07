import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MonthBar from "../components/MonthBar";
import PageShell from "../components/PageShell";

describe("MonthBar (#264)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 7, 12, 0, 0)); // November 2026
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the current month as Live, with the base currency, and no way past it", () => {
    const onMonthChange = vi.fn();
    render(<MonthBar month="2026-11" onMonthChange={onMonthChange} />);

    const bar = screen.getByRole("group", { name: "Month and currency" });
    expect(bar).toHaveTextContent("November 2026");
    expect(bar).toHaveTextContent("Live");
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next month (December 2026)" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Back to/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous month (October 2026)" }));
    expect(onMonthChange).toHaveBeenCalledWith("2026-10");
  });

  it("steps through past months and offers a way back to the current one", () => {
    const onMonthChange = vi.fn();
    render(<MonthBar month="2026-01" onMonthChange={onMonthChange} />);

    expect(screen.getByRole("status")).toHaveTextContent("Past month");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous month (December 2025)" }));
    expect(onMonthChange).toHaveBeenLastCalledWith("2025-12");

    fireEvent.click(screen.getByRole("button", { name: "Next month (February 2026)" }));
    expect(onMonthChange).toHaveBeenLastCalledWith("2026-02");

    fireEvent.click(screen.getByRole("button", { name: "Back to Nov 2026" }));
    expect(onMonthChange).toHaveBeenLastCalledWith("2026-11");
  });

  it("is rendered by PageShell under the title, apart from the header actions", () => {
    render(
      <PageShell title="Stocks" headerActions={<button type="button">Download CSV</button>} monthBar={<MonthBar month="2026-11" onMonthChange={vi.fn()} />}>
        <p>body</p>
      </PageShell>,
    );
    const bar = screen.getByRole("group", { name: "Month and currency" });
    const header = screen.getByRole("heading", { name: "Stocks" }).closest("header");
    expect(header).not.toContainElement(bar);
    expect(header).toContainElement(screen.getByRole("button", { name: "Download CSV" }));
  });
});
