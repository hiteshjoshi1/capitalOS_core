// Credit cards: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { CreditCardAnalytics, CreditCardBalances, CreditCardDetail, CreditCardSummary } from "../types/cards";

export const cardsClient = {
  creditCardSummary: (month: string, baseCurrency = "SGD") =>
    req<CreditCardSummary>(`/spending/credit-cards?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardTransactions: (month: string, baseCurrency = "SGD") =>
    req<CreditCardDetail>(`/spending/credit-card-transactions?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  creditCardBalances: (baseCurrency = "SGD") =>
    req<CreditCardBalances>(`/spending/credit-card-balances?base_currency=${encodeURIComponent(baseCurrency)}`),
  // A statement balance typed in by hand (#300), for a card whose files state none.
  setCreditCardBalance: (
    accountId: number,
    payload: { as_of_date: string; owed: number; due_date?: string | null; minimum_due?: number | null },
    baseCurrency = "SGD",
  ) =>
    req<CreditCardBalances>(
      `/spending/credit-card-balances/${encodeURIComponent(String(accountId))}?base_currency=${encodeURIComponent(baseCurrency)}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  /** A payment due date typed in from a card statement (#352). */
  setCreditCardDue: (
    accountId: number,
    payload: { statement_date: string; due_date: string; amount_due?: number | null; minimum_due?: number | null },
    baseCurrency = "SGD",
  ) =>
    req<CreditCardBalances>(
      `/spending/credit-card-dues/${encodeURIComponent(String(accountId))}?base_currency=${encodeURIComponent(baseCurrency)}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  creditCardAnalytics: (month: string, baseCurrency = "SGD", months = 12, accountId?: number | null) =>
    req<CreditCardAnalytics>(
      `/spending/credit-card-analytics?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}&months=${encodeURIComponent(String(months))}${
        accountId != null ? `&account_id=${encodeURIComponent(String(accountId))}` : ""
      }`,
    ),
};
