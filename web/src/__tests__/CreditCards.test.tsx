import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import CreditCards from "../routes/CreditCards";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { CreditCardDetail } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    creditCardTransactions: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

const detailFixture: CreditCardDetail = {
  month: "2026-02",
  base_currency: "SGD",
  total_spend: 2990,
  cards: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      credit_limit: 20000,
      statement_day: 20,
      due_day: 25,
      due_date: "2026-02-25",
      current_due: 2990,
      utilization: 0.1495,
    },
  ],
  transactions: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      ts: "2026-02-22T12:00:00+00:00",
      description: "Netflix",
      amount: -1210,
      type: "EXPENSE",
      category: "Groceries",
      merchant_counterparty: "Netflix",
      notes: "Annual plan",
    },
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      ts: "2026-02-20T12:00:00+00:00",
      description: "Hawker Center",
      amount: -1780,
      type: "EXPENSE",
      category: "Dining",
      merchant_counterparty: "Hawker Center",
      notes: "Weekend meals",
    },
  ],
  top_purchases: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      ts: "2026-02-20T12:00:00+00:00",
      description: "Hawker Center",
      amount: -1780,
      type: "EXPENSE",
      category: "Dining",
      merchant_counterparty: "Hawker Center",
      notes: "Weekend meals",
    },
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      ts: "2026-02-22T12:00:00+00:00",
      description: "Netflix",
      amount: -1210,
      type: "EXPENSE",
      category: "Groceries",
      merchant_counterparty: "Netflix",
      notes: "Annual plan",
    },
  ],
  recurring_payments: [
    {
      account_id: 11,
      account_name: "DBS Credit Card",
      card_name: "DBS Altitude",
      issuer: "DBS",
      merchant_counterparty: "Netflix",
      months_present: 3,
      current_month_amount: 1210,
    },
  ],
};

describe("CreditCards route", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockApi.creditCardTransactions.mockResolvedValue(detailFixture);
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    cleanup();
  });

  it("renders card breakdown, top purchases, recurring payments, and transactions", async () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <CreditCards />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Card Breakdown")).toBeInTheDocument();
    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");

    expect(screen.getByText("Configured cards: 1")).toBeInTheDocument();
    expect(screen.getByText("Top Purchases")).toBeInTheDocument();
    expect(screen.getByText("Recurring Payments")).toBeInTheDocument();
    expect(screen.getByText("All Transactions")).toBeInTheDocument();
    expect(screen.getAllByText("Netflix").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Month")).toHaveValue(currentMonthYYYYMM());
  });

  it("renders empty states when no credit card data exists", async () => {
    mockApi.creditCardTransactions.mockResolvedValueOnce({
      month: "2026-02",
      base_currency: "SGD",
      total_spend: 0,
      cards: [],
      transactions: [],
      top_purchases: [],
      recurring_payments: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CreditCards />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Card Breakdown")).toBeInTheDocument();
    expect(screen.getByText("No purchases for this month.")).toBeInTheDocument();
    expect(screen.getByText("No recurring payments detected in the last 3 months.")).toBeInTheDocument();
    expect(screen.getAllByText("No credit card transactions for this month.").length).toBeGreaterThan(0);
  });

  it("keeps month fixed when base currency changes", async () => {
    const user = userEvent.setup();

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CreditCards />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Card Breakdown");
    await user.selectOptions(screen.getByLabelText("Base currency"), "USD");

    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith(currentMonthYYYYMM(), "SGD");
    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith(currentMonthYYYYMM(), "USD");
    expect(screen.getByLabelText("Month")).toHaveValue(currentMonthYYYYMM());
  });

  it("uses the persisted dashboard month and updates it when changed", async () => {
    window.localStorage.setItem("capitalos.selectedMonth", "2026-02");

    render(
      <ThemeProvider>
        <MemoryRouter>
          <CreditCards />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Card Breakdown")).toBeInTheDocument();
    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith("2026-02", "SGD");

    fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-03" } });

    expect(mockApi.creditCardTransactions).toHaveBeenCalledWith("2026-03", "SGD");
    expect(window.localStorage.getItem("capitalos.selectedMonth")).toBe("2026-03");
  });
});
