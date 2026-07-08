import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import AllocationCard from "../components/dashboard/AllocationCard";
import CreditCardCard from "../components/dashboard/CreditCardCard";
import DashboardHeader from "../components/dashboard/DashboardHeader";
import PlaceholderCard from "../components/dashboard/PlaceholderCard";

const formatMoney = (value?: number) => (value == null ? "—" : `S$ ${value.toFixed(0)}`);

describe("dashboard components", () => {
  it("renders allocation rows and empty fallback", () => {
    const { rerender } = render(
      <AllocationCard
        title="Allocation"
        firstColumnLabel="Bucket"
        rows={[{ key: "US", value: 10, percent: 50 }]}
        emptyLabel="No rows"
        formatMoney={formatMoney}
      />,
    );
    expect(screen.getByText("US")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();

    rerender(
      <AllocationCard
        title="Allocation"
        firstColumnLabel="Bucket"
        rows={[]}
        emptyLabel="No rows"
        formatMoney={formatMoney}
      />,
    );
    expect(screen.getByText("No rows")).toBeInTheDocument();
  });

  it("renders credit-card summaries with and without cards", () => {
    const { rerender } = render(
      <MemoryRouter>
        <CreditCardCard
          month="2026-03"
          formatMoney={formatMoney}
          summary={{
            month: "2026-03",
            base_currency: "SGD",
            total_spend: 1200,
            cards: [
              {
                account_id: 1,
                account_name: "Card A",
                card_name: "Card A",
                issuer: "DBS",
                credit_limit: 10000,
                statement_day: 1,
                due_day: 10,
                due_date: "2026-03-10",
                current_due: 700,
                utilization: 0.07,
              },
            ],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Highest spend cards")).toBeInTheDocument();
    expect(screen.getByText("Card A")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <CreditCardCard
          month="2026-03"
          formatMoney={formatMoney}
          summary={{
            month: "2026-03",
            base_currency: "SGD",
            total_spend: 0,
            cards: [],
          }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("No credit card transactions for this month.")).toBeInTheDocument();
  });

  it("supports dashboard header interactions and menu close handlers", () => {
    const onMonthChange = vi.fn();
    const onBaseCurrencyChange = vi.fn();
    const onToggleTheme = vi.fn();

    render(
      <MemoryRouter>
        <DashboardHeader
          health="ok"
          asOf="2026-03-06"
          month="2026-03"
          baseCurrency="SGD"
          theme="dark"
          onMonthChange={onMonthChange}
          onBaseCurrencyChange={onBaseCurrencyChange}
          onToggleTheme={onToggleTheme}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText("Theme: Dark"));
    expect(onToggleTheme).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Base currency"), { target: { value: "USD" } });
    expect(onBaseCurrencyChange).toHaveBeenCalledWith("USD");

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-02" } });
    expect(onMonthChange).toHaveBeenCalledWith("2026-02");

    const details = screen.getByLabelText("User menu").closest("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent.keyDown(document, { key: "Escape" });
    expect(details.open).toBe(false);

    details.open = true;
    fireEvent.pointerDown(document.body);
    expect(details.open).toBe(false);
  });

  it("renders placeholder footer conditionally", () => {
    const { rerender } = render(
      <PlaceholderCard title="Placeholder" description="Body" footer="More info" />,
    );
    expect(screen.getByText("More info")).toBeInTheDocument();

    rerender(<PlaceholderCard title="Placeholder" description="Body" />);
    expect(screen.queryByText("More info")).not.toBeInTheDocument();
  });
});
