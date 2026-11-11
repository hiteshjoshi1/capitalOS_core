// Market data and FX: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { FxBackfillPlan, FxBackfillResult, MarketDataExchangeStatus, MarketDataRun, MarketDataTickerSet, MarketDataTickerTest, MarketDataUnpriced } from "../types/marketData";

export const marketDataClient = {
  marketDataStatus: () => req<{ status: MarketDataExchangeStatus[] }>("/market-data/status"),
  marketDataRuns: (limit = 50) =>
    req<{ runs: MarketDataRun[] }>(`/market-data/runs?limit=${encodeURIComponent(String(limit))}`),
  fxBackfillPlan: (baseCurrency: string) =>
    req<FxBackfillPlan>(`/fx/backfill-plan?base_currency=${encodeURIComponent(baseCurrency)}`),
  fxBackfill: (baseCurrency: string) =>
    req<FxBackfillResult>(`/fx/backfill?base_currency=${encodeURIComponent(baseCurrency)}`, { method: "POST" }),
  marketDataRefreshNow: (adminKey?: string, exchange?: string) =>
    req<{ status: string; exchanges: Array<Record<string, unknown>> }>(
      `/market-data/refresh-now${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ""}`,
      {
        method: "POST",
        headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
      },
    ),
  marketDataUnpriced: () => req<MarketDataUnpriced>("/market-data/unpriced"),
  marketDataTickerTest: (yahooSymbol: string, exchangeCode?: string | null) =>
    req<MarketDataTickerTest>("/market-data/ticker-test", {
      method: "POST",
      body: JSON.stringify({ yahoo_symbol: yahooSymbol, exchange_code: exchangeCode ?? null }),
    }),
  marketDataSetTicker: (assetId: number, exchangeCode: string, yahooSymbol: string) =>
    req<MarketDataTickerSet>("/market-data/ticker", {
      method: "POST",
      body: JSON.stringify({ asset_id: assetId, exchange_code: exchangeCode, yahoo_symbol: yahooSymbol }),
    }),
};
