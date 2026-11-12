// Wealth pages: dashboard, history, risk, bridge, stocks: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { CashDeposits, DashboardBootstrap, DashboardNetWorthChange, DashboardSummary, GeographyExposure, HistoryGenerateStatus, MarkVisitResult, MonthBridge, NetWorthSinceUpdate, PlatformAllocation, RealisedPeriodQuery, RealisedPnl, RiskSummary, RiskThresholdsSetting, SinceLastVisit, SpanBridge, StockExposure, StockHoldingsSummary, WealthTimeline, WealthTimelineBackfillResult, WealthTopMovers } from "../types/wealth";

export const wealthClient = {
  dashboardBootstrap: (month: string, baseCurrency = "SGD") =>
    req<DashboardBootstrap>(`/dashboard/bootstrap?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  dashboardNetWorthChange: (month: string, baseCurrency = "SGD", compare = "prev_month,prev_year") =>
    req<DashboardNetWorthChange>(`/dashboard/net-worth-change?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}&compare=${encodeURIComponent(compare)}`),
  netWorthTimeline: (months: number, baseCurrency = "SGD") =>
    req<WealthTimeline>(`/dashboard/net-worth-timeline?months=${encodeURIComponent(String(months))}&base_currency=${encodeURIComponent(baseCurrency)}`),
  netWorthTimelineBackfill: (months: number, baseCurrency = "SGD") =>
    req<WealthTimelineBackfillResult>(
      `/dashboard/net-worth-timeline/backfill?months=${encodeURIComponent(String(months))}&base_currency=${encodeURIComponent(baseCurrency)}`,
      { method: "POST" },
    ),
  /** Starts "Generate history" in the background (#292); no `months` = the span of your data. */
  netWorthTimelineGenerate: (baseCurrency = "SGD", months?: number) =>
    req<HistoryGenerateStatus>(
      `/dashboard/net-worth-timeline/generate?base_currency=${encodeURIComponent(baseCurrency)}${
        months == null ? "" : `&months=${encodeURIComponent(String(months))}`
      }`,
      { method: "POST" },
    ),
  netWorthTimelineGenerateStatus: (baseCurrency = "SGD") =>
    req<HistoryGenerateStatus>(
      `/dashboard/net-worth-timeline/generate/status?base_currency=${encodeURIComponent(baseCurrency)}`,
    ),
  netWorthTimelineMovers: (month: string, baseCurrency = "SGD", limit = 5) =>
    req<WealthTopMovers>(
      `/dashboard/net-worth-timeline/${encodeURIComponent(month)}/movers?base_currency=${encodeURIComponent(baseCurrency)}&limit=${encodeURIComponent(String(limit))}`,
    ),
  dashboardSummary: (month: string, compare?: string, baseCurrency = "SGD", skipNetworth = false) =>
  req<DashboardSummary>(`/dashboard/summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}${compare ? `&compare=${encodeURIComponent(compare)}` : ""}${skipNetworth ? "&skip_networth=true" : ""}`),
  riskSummary: (month: string, baseCurrency = "SGD") =>
    req<RiskSummary>(`/dashboard/risk-summary?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  riskThresholds: () => req<RiskThresholdsSetting>("/dashboard/risk-thresholds"),
  saveRiskThresholds: (payload: RiskThresholdsSetting) =>
    req<RiskThresholdsSetting>("/dashboard/risk-thresholds", { method: "PUT", body: JSON.stringify(payload) }),
  spanBridge: (fromMonth: string, toMonth: string, baseCurrency = "SGD") =>
    req<SpanBridge>(
      `/dashboard/bridge?from=${encodeURIComponent(fromMonth)}&to=${encodeURIComponent(toMonth)}&base_currency=${encodeURIComponent(baseCurrency)}`,
    ),
  monthBridge: (month: string, baseCurrency = "SGD") =>
    req<MonthBridge>(`/dashboard/month-bridge?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  realisedPnl: (month: string, baseCurrency = "SGD", period?: RealisedPeriodQuery) => {
    const params = new URLSearchParams({ month, base_currency: baseCurrency });
    if (period) {
      params.set("period", period.period);
      if (period.year != null) params.set("year", String(period.year));
      if (period.from) params.set("from", period.from);
      if (period.to) params.set("to", period.to);
    }
    return req<RealisedPnl>(`/dashboard/realised-pnl?${params.toString()}`);
  },
  stockHoldingsSummary: (month: string, baseCurrency = "SGD") =>
    req<StockHoldingsSummary>(`/dashboard/stock-holdings?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  // #408 (U3): "Since your last visit". markVisit moves the stored mark (force: Dismiss).
  sinceLastVisit: (baseCurrency = "SGD") =>
    req<SinceLastVisit>(`/dashboard/since-last-visit?base_currency=${encodeURIComponent(baseCurrency)}`),
  markVisit: (baseCurrency = "SGD", force = false) =>
    req<MarkVisitResult>(`/dashboard/visit?base_currency=${encodeURIComponent(baseCurrency)}${force ? "&force=true" : ""}`, { method: "POST" }),
  netWorthSinceUpdate: (baseCurrency = "SGD") =>
    req<NetWorthSinceUpdate>(`/dashboard/net-worth-since-update?base_currency=${encodeURIComponent(baseCurrency)}`),
  cashDeposits: (month: string, baseCurrency = "SGD") =>
    req<CashDeposits>(`/dashboard/cash-deposits?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  platformAllocation: (month: string, baseCurrency = "SGD") =>
    req<PlatformAllocation>(`/dashboard/platform-allocation?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  dashboardGeographyExposure: (month: string, baseCurrency = "SGD") =>
    req<GeographyExposure>(`/dashboard/geography-exposure?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
  stockExposure: (month: string, baseCurrency = "SGD") =>
    req<StockExposure>(`/dashboard/stock-exposure?month=${encodeURIComponent(month)}&base_currency=${encodeURIComponent(baseCurrency)}`),
};
