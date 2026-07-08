import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type { StockHoldingsSummary } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import ExposurePieCard from "../components/ExposurePieCard";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import ValueTrendChart from "../components/ValueTrendChart";

type LoadState = "idle" | "loading" | "ready" | "error";
type StockColumnKey = "shares" | "purchasePrice" | "currentPrice" | "pnl" | "percentNetWorth" | "quoteFreshness";

const PAGE_SIZE = 20;
const STOCK_COLUMN_STORAGE_KEY = "capitalos.stockHoldings.visibleColumns";
const STOCK_COLUMN_OPTIONS: Array<{ key: StockColumnKey; label: string; align?: "right" }> = [
  { key: "shares", label: "Shares", align: "right" },
  { key: "purchasePrice", label: "Purchase Price", align: "right" },
  { key: "currentPrice", label: "Current Price", align: "right" },
  { key: "pnl", label: "Profit & Loss", align: "right" },
  { key: "percentNetWorth", label: "% NW", align: "right" },
  { key: "quoteFreshness", label: "Quote freshness" },
];
const DEFAULT_VISIBLE_STOCK_COLUMNS: Record<StockColumnKey, boolean> = {
  shares: true,
  purchasePrice: true,
  currentPrice: true,
  pnl: true,
  percentNetWorth: true,
  quoteFreshness: true,
};

const loadVisibleStockColumns = (): Record<StockColumnKey, boolean> => {
  const defaults = { ...DEFAULT_VISIBLE_STOCK_COLUMNS };
  if (typeof window === "undefined") {
    return defaults;
  }

  const stored = window.localStorage.getItem(STOCK_COLUMN_STORAGE_KEY);
  if (!stored) {
    return defaults;
  }

  try {
    const parsed = JSON.parse(stored) as Partial<Record<StockColumnKey, unknown>>;
    return STOCK_COLUMN_OPTIONS.reduce<Record<StockColumnKey, boolean>>((columns, option) => {
      const storedValue = parsed[option.key];
      columns[option.key] = typeof storedValue === "boolean"
        ? storedValue
        : DEFAULT_VISIBLE_STOCK_COLUMNS[option.key];
      return columns;
    }, defaults);
  } catch {
    return defaults;
  }
};

export default function StockHoldings() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<StockHoldingsSummary | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [visibleColumns, setVisibleColumns] = useState<Record<StockColumnKey, boolean>>(loadVisibleStockColumns);
  const columnMenuRef = useRef<HTMLDetailsElement>(null);

  // Close the column menu when clicking outside it
  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (columnMenuRef.current && !columnMenuRef.current.contains(event.target as Node)) {
        columnMenuRef.current.open = false;
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const handleMonthChange = (nextMonth: string) => {
    setVisibleCount(PAGE_SIZE);
    setMonth(nextMonth);
  };

  const handleBaseCurrencyChange = (nextBaseCurrency: string) => {
    setVisibleCount(PAGE_SIZE);
    setBaseCurrency(nextBaseCurrency);
  };

  const handleColumnToggle = (key: StockColumnKey) => {
    setVisibleColumns((current) => ({
      ...current,
      [key]: !current[key],
    }));
  };

  const loadSummary = useCallback(async () => {
    setErr("");
    setState("loading");
    const stockData = await api.stockHoldingsSummary(month, baseCurrency);
    setSummary(stockData);
    setState("ready");
  }, [month, baseCurrency]);

  useEffect(() => {
    (async () => {
      try {
        await loadSummary();
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [loadSummary]);

  useEffect(() => {
    window.localStorage.setItem(STOCK_COLUMN_STORAGE_KEY, JSON.stringify(visibleColumns));
  }, [visibleColumns]);

  const onRefresh = async () => {
    try {
      setRefreshing(true);
      await api.marketDataRefreshNow();
      await loadSummary();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setState("error");
    } finally {
      setRefreshing(false);
    }
  };

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatCompactMoney = (value?: number | null) =>
    value == null
      ? "—"
      : `${currencyPrefix} ${value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`;
  const formatQuantity = (value?: number | null) =>
    value == null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  const formatNativeMoney = (value?: number | null, quoteCurrency?: string, maximumFractionDigits = 2) => {
    if (value == null || !quoteCurrency) {
      return "—";
    }
    return `${quoteCurrency.toUpperCase()} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  };
  const formatPnl = (holding: StockHoldingsSummary["top_holdings"][number]) => {
    if (
      holding.quantity == null
      || holding.avg_cost == null
      || holding.latest_price == null
      || !holding.quote_currency
    ) {
      return { amount: "—", pct: null, positive: true };
    }
    const pnl = holding.quantity * (holding.latest_price - holding.avg_cost);
    const pnlPct = holding.avg_cost > 0 ? ((holding.latest_price - holding.avg_cost) / holding.avg_cost) * 100 : null;
    return {
      amount: `${pnl >= 0 ? "+" : "-"}${formatNativeMoney(Math.abs(pnl), holding.quote_currency)}`,
      pct: pnlPct,
      positive: pnl >= 0,
    };
  };
  const holdings = useMemo(() => summary?.top_holdings ?? [], [summary]);
  const visibleHoldings = holdings.slice(0, visibleCount);
  const visibleColumnCount = 1 + STOCK_COLUMN_OPTIONS.filter((option) => visibleColumns[option.key]).length;
  const hasMore = visibleCount < holdings.length;
  const hasPrevious = visibleCount > PAGE_SIZE;
  const stockCurrentTotal = summary?.stock_current_total ?? 0;
  const geographyPieItems = useMemo(
    () => (summary?.geography_breakdown ?? [])
      .filter((item) => item.current_value > 0)
      .map((item) => ({
        label: item.geography,
        value: item.current_value,
        percent: stockCurrentTotal > 0 ? (item.current_value / stockCurrentTotal) * 100 : 0,
      })),
    [stockCurrentTotal, summary?.geography_breakdown],
  );
  const platformPieItems = useMemo(
    () => (summary?.platform_breakdown ?? [])
      .filter((item) => item.current_value > 0)
      .map((item) => ({
        label: formatPlatformLabel(item.key),
        value: item.current_value,
        percent: item.percent,
      })),
    [summary?.platform_breakdown],
  );

  return (
    <PageShell
      title="Stock Holdings"
      subtitle="Current equity holdings with quote freshness and snapshot geography comparisons."
      activeRoute="/holdings"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      headerActions={
        <>
          <button className="btn" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Refreshing..." : "Refresh now"}
          </button>
          <MonthControl month={month} onMonthChange={handleMonthChange} />
          <label className="coPillBtn">
                        <span aria-hidden="true">{baseCurrency}</span>
            <select
              className="coPillBtnInput"
              aria-label="Base currency"
              value={baseCurrency}
              onChange={(event) => handleBaseCurrencyChange(event.target.value)}
            >
              <option value="SGD">SGD</option>
              <option value="USD">USD</option>
              <option value="HKD">HKD</option>
              <option value="INR">INR</option>
            </select>
          </label>
        </>
      }
    >
      {state === "loading" && <div className="card">Loading…</div>}
      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <div className="wealthOverviewLayout">

          {/* ── Hero: stock value summary ─────────────────────────────── */}
          <article className="coHeroCard">
            <div className="coHeroCardHeader">
              <p className="coHeroEyebrow">CURRENT STOCK VALUE</p>
              <span className="muted" style={{ fontSize: "12px" }}>
                {summary?.as_of_month ?? month}
              </span>
            </div>
            <div className="coHeroValueRow">
              <span className="coHeroValue">{formatMoney(summary?.stock_current_total)}</span>
              {summary?.stock_current_total != null && summary?.stock_snapshot_total != null && summary.stock_snapshot_total > 0 ? (() => {
                const delta = summary.stock_current_total - summary.stock_snapshot_total;
                const pct = (delta / summary.stock_snapshot_total) * 100;
                return (
                  <span className={`coChip${delta >= 0 ? " coChipPositive" : " coChipNegative"}`}>
                    {delta >= 0 ? "+" : ""}{pct.toFixed(1)}%
                  </span>
                );
              })() : null}
            </div>
            {summary?.stock_snapshot_total != null ? (
              <p className="coHeroFreshness">
                Snapshot {formatMoney(summary.stock_snapshot_total)} · {summary.net_worth_snapshot_as_of?.slice(0, 10) ?? "—"}
                {summary.quote_freshness_summary ? ` · ${summary.quote_freshness_summary.fresh} fresh · ${summary.quote_freshness_summary.stale} stale` : ""}
              </p>
            ) : null}
          </article>

          {/* ── Exposure breakdown ────────────────────────────────────── */}
          <section aria-label="Stock exposure breakdown">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">EXPOSURE</p>
                <h2 className="coSectionTitle">Breakdown by geography and platform</h2>
              </div>
            </div>
            <div className="coExposureGrid">
              <ExposurePieCard
                title="Geography Breakdown"
                subtitle={`Stock exposure · snapshot ${summary?.net_worth_snapshot_as_of?.slice(0, 10) ?? "—"}`}
                items={geographyPieItems}
                totalLabel={formatMoney(stockCurrentTotal)}
                formatMoney={formatMoney}
                ariaLabel="Stock geography exposure pie chart"
              />
              <ExposurePieCard
                title="Platform Breakdown"
                subtitle="Stock exposure by broker/platform"
                items={platformPieItems}
                totalLabel={formatMoney(stockCurrentTotal)}
                formatMoney={formatMoney}
                ariaLabel="Stock platform exposure pie chart"
              />
            </div>
          </section>

          {/* ── Trend chart ───────────────────────────────────────────── */}
          <section aria-label="Stock trend">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">HISTORY</p>
                <h2 className="coSectionTitle">Six-Month Stock Trend</h2>
              </div>
              <span className="muted" style={{ fontSize: "13px" }}>
                Ending {summary?.as_of_month ?? month}
              </span>
            </div>
            <div className="card valueTrendCard">
              <div className="valueTrendValue">
                <span>Current stock value</span>
                <strong>{formatMoney(summary?.stock_current_total)}</strong>
              </div>
              <ValueTrendChart
                points={summary?.trend ?? []}
                ariaLabel="Six-month stock trend"
                formatMoney={formatMoney}
                formatCompactMoney={formatCompactMoney}
              />
            </div>
          </section>

          {/* ── Holdings table ────────────────────────────────────────── */}
          <section aria-label="Top holdings">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">POSITIONS</p>
                <h2 className="coSectionTitle">Top Holdings</h2>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span className="muted" style={{ fontSize: "13px" }}>
                  {visibleHoldings.length} of {holdings.length} positions
                </span>
                <details className="stockColumnMenu" ref={columnMenuRef}>
                  <summary className="btn stockColumnSummary">Columns</summary>
                  <div className="stockColumnPanel" aria-label="Visible stock columns">
                    {STOCK_COLUMN_OPTIONS.map((option) => (
                      <label className="stockColumnOption" key={option.key}>
                        <input
                          type="checkbox"
                          checked={visibleColumns[option.key]}
                          onChange={() => handleColumnToggle(option.key)}
                        />
                        <span>{option.label}</span>
                      </label>
                    ))}
                  </div>
                </details>
              </div>
            </div>
            <div className="card stockHoldingsPrimaryCard">
              <div className="stockHoldingsTableWrap">
                <table className="table stockHoldingsTable">
                  <thead>
                    <tr>
                      <th>Asset</th>
                      {visibleColumns.shares && <th className="right">Shares</th>}
                      {visibleColumns.purchasePrice && <th className="right">Purchase Price</th>}
                      {visibleColumns.currentPrice && <th className="right">Current Price</th>}
                      {visibleColumns.pnl && <th className="right">Profit &amp; Loss</th>}
                      {visibleColumns.percentNetWorth && <th className="right">% NW</th>}
                      {visibleColumns.quoteFreshness && <th>Quote freshness</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleHoldings.map((h, idx) => {
                      const pnl = formatPnl(h);
                      return (
                        <tr key={h.asset_id ?? `${h.symbol}-${idx}`}>
                          <td>
                            <div className="stockHoldingsAssetCell">
                              <div className="stockHoldingsSymbol">{h.symbol}</div>
                              <div className="stockHoldingsAssetMeta">
                                <span>{h.platform ?? "—"}</span>
                                <span>{h.geo ?? "—"}</span>
                              </div>
                            </div>
                          </td>
                          {visibleColumns.shares && (
                            <td className="right stockHoldingsQuantityCell">{formatQuantity(h.quantity)}</td>
                          )}
                          {visibleColumns.purchasePrice && (
                            <td className="right stockHoldingsPriceCell">{formatNativeMoney(h.avg_cost, h.quote_currency)}</td>
                          )}
                          {visibleColumns.currentPrice && (
                            <td className="right stockHoldingsPriceCell">{formatNativeMoney(h.latest_price, h.quote_currency)}</td>
                          )}
                          {visibleColumns.pnl && (
                            <td className={`right stockHoldingsPnlCell ${pnl.positive ? "good" : "bad"}`}>
                              <div>{pnl.amount}</div>
                              {pnl.pct == null ? null : <small>{pnl.pct >= 0 ? "+" : ""}{pnl.pct.toFixed(1)}%</small>}
                            </td>
                          )}
                          {visibleColumns.percentNetWorth && (
                            <td className="right stockHoldingsPercentCell">
                              <div>{h.percent_of_networth.toFixed(1)}%</div>
                              <small>{formatMoney(h.value)}</small>
                            </td>
                          )}
                          {visibleColumns.quoteFreshness && (
                            <td>
                              <div>{h.quote_freshness_status ?? "missing"}</div>
                              <small className="muted">
                                {h.latest_trade_date?.slice(0, 10) ?? "—"}
                                {h.price_provider ? ` · ${h.price_provider}` : ""}
                              </small>
                            </td>
                          )}
                        </tr>
                      );
                    })}
                    {summary && holdings.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={visibleColumnCount}>No holdings available.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {holdings.length > 0 ? (
                <div className="stockHoldingsControls">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setVisibleCount((current) => Math.max(PAGE_SIZE, current - PAGE_SIZE))}
                    disabled={!hasPrevious}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setVisibleCount((current) => Math.min(holdings.length, current + PAGE_SIZE))}
                    disabled={!hasMore}
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      )}
    </PageShell>
  );
}
