// Cash flow, spending and categories: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { CashFlowDetail, CashFlowTrend, CategoryOverrideBulkPayload, CategoryOverrideBulkResult, CategoryOverridePayload, CategoryResolution, CategoryTaxonomy, SpendingSummary, UnmappedTransaction } from "../types/cashFlow";

export const cashFlowClient = {
  categories: () => req<CategoryTaxonomy[]>("/categories"),
  unmappedTransactions: (month: string, accountId?: number) =>
    req<UnmappedTransaction[]>(
      `/categories/unmapped?month=${encodeURIComponent(month)}${
        accountId == null ? "" : `&account_id=${encodeURIComponent(String(accountId))}`
      }`
    ),
  categoryOverride: (payload: CategoryOverridePayload) =>
    req<CategoryResolution>("/categories/override", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  categoryOverrideBulk: (payload: CategoryOverrideBulkPayload) =>
    req<CategoryOverrideBulkResult>("/categories/override-bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  spendingSummary: (month: string, baseCurrency = "SGD") =>
    req<SpendingSummary>(`/spending/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  cashFlowDetail: (month: string, baseCurrency = "SGD") =>
    req<CashFlowDetail>(`/spending/cash-flow-detail?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  cashFlowTrend: (month: string, baseCurrency = "SGD") =>
    req<CashFlowTrend>(`/spending/cash-flow-trend?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
};
