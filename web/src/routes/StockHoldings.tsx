import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { StockHolding } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { monthEndCloseDate, snapshotMonthOf, useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import { deltaPercent, noDataFor } from "../lib/delta";
import { hasLivePrice, holdingPriceAge } from "../lib/priceAge";
import "../App.css";
import Delta from "../components/Delta";
import ExposurePieCard from "../components/ExposurePieCard";
import MonthControl from "../components/MonthControl";
import PriceFallbackInfo from "../components/PriceFallbackInfo";
import StockMonthChange from "../components/StockMonthChange";
import PageShell from "../components/PageShell";
import ValueTrendChart from "../components/ValueTrendChart";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import LoadError from "../components/LoadError";

type StockColumnKey = "shares" | "purchasePrice" | "currentPrice" | "monthChange" | "pnl" | "percentNetWorth" | "quoteFreshness";

const PAGE_SIZE = 20;
const MOBILE_BREAKPOINT_PX = 900;
const STOCK_COLUMN_STORAGE_KEY = "capitalos.stockHoldings.visibleColumns";
const STOCK_COLUMN_OPTIONS: Array<{ key: StockColumnKey; label: string; align?: "right" }> = [
  { key: "shares", label: "Shares", align: "right" },
  { key: "purchasePrice", label: "Purchase Price", align: "right" },
  { key: "currentPrice", label: "Current Price", align: "right" },
  { key: "monthChange", label: "Change vs month-end", align: "right" },
  { key: "pnl", label: "Profit & Loss", align: "right" },
  { key: "percentNetWorth", label: "% NW", align: "right" },
  { key: "quoteFreshness", label: "Quote freshness" },
];
const DEFAULT_VISIBLE_STOCK_COLUMNS: Record<StockColumnKey, boolean> = {
  shares: true,
  purchasePrice: true,
  currentPrice: true,
  monthChange: true,
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
  const [refreshErr, setRefreshErr] = useState<string>("");
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency] = useBaseCurrency();
  const resource = useApiResource(resourceKey("stockHoldingsSummary", month, baseCurrency), () =>
    api.stockHoldingsSummary(month, baseCurrency),
  );
  const summary = resource.data ?? null;
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [visibleColumns, setVisibleColumns] = useState<Record<StockColumnKey, boolean>>(loadVisibleStockColumns);
  const [isMobile, setIsMobile] = useState<boolean>(() =>
    typeof window === "undefined" ? false : window.innerWidth <= MOBILE_BREAKPOINT_PX,
  );
  const columnMenuRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= MOBILE_BREAKPOINT_PX);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

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

  // The base currency is shared (#150): back to the first page whenever it changes.
  const [pagedCurrency, setPagedCurrency] = useState(baseCurrency);
  if (pagedCurrency !== baseCurrency) {
    setPagedCurrency(baseCurrency);
    setVisibleCount(PAGE_SIZE);
  }

  const handleColumnToggle = (key: StockColumnKey) => {
    setVisibleColumns((current) => ({
      ...current,
      [key]: !current[key],
    }));
  };

  useEffect(() => {
    window.localStorage.setItem(STOCK_COLUMN_STORAGE_KEY, JSON.stringify(visibleColumns));
  }, [visibleColumns]);

  const onRefresh = async () => {
    try {
      setRefreshing(true);
      setRefreshErr("");
      await api.marketDataRefreshNow();
      await resource.reload();
    } catch (e: unknown) {
      setRefreshErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  // The currency the shown numbers are in (the previous one while a switch loads).
  const shownCurrency = summary?.base_currency || baseCurrency;
  const formatMoney = (value?: number | null, decimals = 0) => fmt.formatMoney(value, shownCurrency, { decimals });
  const formatCompactMoney = (value?: number | null) => fmt.formatMoneyCompact(value, shownCurrency);
  const formatQuantity = (value?: number | null) => fmt.formatNumber(value, 4);
  /** Prices and native P&L: 2 decimals, in the quote currency. */
  const formatNativeMoney = (value?: number | null, quoteCurrency?: string, decimals = 2) =>
    quoteCurrency ? fmt.formatMoney(value, quoteCurrency, { decimals }) : fmt.MISSING;
  /** P&L in the base currency (at the rate the holding's value implies), the local
   * currency in the tooltip: the same on the table and the mobile card (#251). */
  const formatPnl = (holding: StockHolding) => {
    if (
      holding.quantity == null
      || holding.avg_cost == null
      || holding.latest_price == null
      || !holding.quote_currency
    ) {
      return { amount: "—", native: null, pct: null, positive: true };
    }
    const nativePnl = holding.quantity * (holding.latest_price - holding.avg_cost);
    const native = fmt.formatSignedMoney(nativePnl, holding.quote_currency, { decimals: 2 });
    const pnlPct = holding.avg_cost > 0 ? ((holding.latest_price - holding.avg_cost) / holding.avg_cost) * 100 : null;
    const nativeValue = holding.quantity * holding.latest_price;
    if (nativeValue <= 0 || holding.value == null) {
      return { amount: native, native: null, pct: pnlPct, positive: nativePnl >= 0 };
    }
    const pnl = nativePnl * (holding.value / nativeValue);
    return {
      amount: fmt.formatSignedMoney(pnl, shownCurrency),
      native: holding.quote_currency.toUpperCase() === shownCurrency.toUpperCase() ? null : `In ${holding.quote_currency}: ${native}`,
      pct: pnlPct,
      positive: pnl >= 0,
    };
  };
  const formatGeoLabel = (geo?: string | null) => {
    const normalized = (geo ?? "").toUpperCase();
    const labels: Record<string, string> = {
      HK: "Hong Kong",
      IN: "India",
      SG: "Singapore",
      US: "United States",
    };
    return labels[normalized] ?? geo ?? "—";
  };
  const formatExchangeLabel = (holding: StockHolding) =>
    holding.exchange_code ?? holding.quote_currency ?? holding.asset_class;
  const formatFreshnessLabel = (status?: string | null) => {
    if (!status) {
      return "Missing";
    }
    return `${status.slice(0, 1).toUpperCase()}${status.slice(1).toLowerCase()}`;
  };
  const holdings = useMemo(() => summary?.top_holdings ?? [], [summary]);
  // #251: holdings held at the compare month-end and sold since, listed after the
  // held ones (value 0, "Sold"), so the rows' changes add up to the headline's.
  const soldHoldings = useMemo(() => summary?.sold_holdings ?? [], [summary]);
  const rows = useMemo(() => [...holdings, ...soldHoldings], [holdings, soldHoldings]);
  const compareCloseDate = monthEndCloseDate(summary?.compare_boundary_at);
  const compareLabel = compareCloseDate
    ? fmt.formatDate(compareCloseDate)
    : fmt.formatMonth(summary?.compare_month, "medium");
  // #224: freshness only means something on the live month; a past month is valued
  // at its statements.
  const isLive = summary?.is_live === true;
  const noLivePriceCount = isLive
    ? (summary?.quote_freshness_summary?.no_live_price ?? holdings.filter((h) => !hasLivePrice(h)).length)
    : 0;
  const stockSnapshotTotal = summary?.stock_snapshot_total;
  const stockMissingReason = summary?.stock_snapshot_missing ? noDataFor(summary.compare_month) : null;
  const escapeCsvValue = (value: string | number | null | undefined): string => {
    if (value == null) return "";
    const text = String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const handleDownloadCsv = () => {
    const rows = holdings.filter((h) => h.asset_class === "STOCK" || h.asset_class === "FUND");
    const header = ["Symbol", "Name", "Quantity", "Buy Price", "Current Price", "Currency", "Profit/Loss", "P/L %"];
    const lines = [header.map(escapeCsvValue).join(",")];
    for (const h of rows) {
      const hasPnlInputs = h.quantity != null && h.avg_cost != null && h.latest_price != null;
      const pnl = hasPnlInputs ? h.quantity! * (h.latest_price! - h.avg_cost!) : null;
      const pnlPct = hasPnlInputs && h.avg_cost! > 0
        ? ((h.latest_price! - h.avg_cost!) / h.avg_cost!) * 100
        : null;
      lines.push(
        [
          h.symbol,
          h.name ?? "",
          h.quantity ?? "",
          h.avg_cost ?? "",
          h.latest_price ?? "",
          h.quote_currency ?? "",
          pnl != null ? pnl.toFixed(2) : "",
          pnlPct != null ? pnlPct.toFixed(2) : "",
        ]
          .map(escapeCsvValue)
          .join(","),
      );
    }
    const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const dateLabel = summary?.is_live ? new Date().toISOString().slice(0, 10) : (summary?.as_of_month ?? month);
    const link = document.createElement("a");
    link.href = url;
    link.download = `stock-holdings-${dateLabel}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };
  const visibleHoldings = rows.slice(0, visibleCount);
  const visibleColumnCount = 1 + STOCK_COLUMN_OPTIONS.filter((option) => visibleColumns[option.key]).length;
  const hasMore = visibleCount < rows.length;
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
  const geographyPerformanceItems = useMemo(
    () => (summary?.geography_performance ?? [])
      .filter((item) => item.current_value > 0 || item.snapshot_value > 0)
      .sort((a, b) => b.delta_pct != null && a.delta_pct != null ? b.delta_pct - a.delta_pct : (b.delta_abs - a.delta_abs)),
    [summary?.geography_performance],
  );
  const geographyPerformanceAsOfLabel = useMemo(() => {
    const raw = summary?.geography_performance_as_of;
    if (!raw) return null;
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) return null;
    return fmt.formatDateTime(raw);
  }, [summary?.geography_performance_as_of]);

  return (
    <PageShell
      title="Stock Holdings"
      subtitle="Equity holdings as of any month, with quote freshness and month-over-month comparisons."
      headerActions={
        <>
          <button
            className="btn stockHoldingsDownloadBtn"
            onClick={handleDownloadCsv}
            disabled={holdings.length === 0}
            title="Download currently held stocks as CSV"
          >
            Download CSV
          </button>
          <MonthControl month={month} onMonthChange={handleMonthChange} />
          <BaseCurrencyPicker />
        </>
      }
    >
      {resource.isLoading && <div className="card" role="status">Loading…</div>}
      {(resource.error || refreshErr) && (
        <LoadError title="Couldn't load stock holdings" error={resource.error?.message ?? refreshErr} onRetry={() => void resource.reload().catch(() => undefined)} />
      )}

      {summary && (
        <RefreshingRegion className="wealthOverviewLayout" busy={resource.isFetching}>

          {/* ── Hero: stock value summary ─────────────────────────────── */}
          <article className="coHeroCard">
            <div className="coHeroCardHeader">
              <p className="coHeroEyebrow">{summary?.is_live ? "CURRENT STOCK VALUE" : `STOCK VALUE — ${snapshotMonthOf(summary?.net_worth_boundary_at, summary?.as_of_month ?? month)}`}</p>
              <span className="muted" style={{ fontSize: "12px" }}>
                {summary?.is_live ? `as of ${fmt.formatDate(summary?.net_worth_as_of)}` : "historical snapshot"}
              </span>
            </div>
            <div className="coHeroValueRow">
              <span className="coHeroValue">{formatMoney(summary?.stock_current_total)}</span>
              {summary?.stock_current_total != null && stockSnapshotTotal != null ? (
                <Delta
                  variant="chip"
                  show="pct"
                  abs={summary.stock_current_total - stockSnapshotTotal}
                  compareValue={stockSnapshotTotal}
                  currency={shownCurrency}
                  missingReason={stockMissingReason}
                />
              ) : null}
            </div>
            {stockSnapshotTotal != null && !stockMissingReason ? (
              <p className="coHeroFreshness">
                {/* #232: the previous figure names its month and the date of its holdings. */}
                vs {summary.compare_month ? fmt.formatMonth(summary.compare_month, "medium") : "last month"} ({formatMoney(stockSnapshotTotal)}
                {summary.stock_snapshot_as_of ? `, holdings as of ${fmt.formatDate(summary.stock_snapshot_as_of)}` : ""}):{" "}
                <Delta
                  abs={(summary.stock_current_total ?? 0) - stockSnapshotTotal}
                  compareValue={stockSnapshotTotal}
                  currency={shownCurrency}
                />
              </p>
            ) : null}
            {isLive && summary.quote_freshness_summary ? (
              <p className="coHeroFreshness" data-testid="stock-price-freshness">
                Prices: {summary.quote_freshness_summary.fresh} fresh · {summary.quote_freshness_summary.stale} stale
                {noLivePriceCount > 0 ? (
                  <>
                    {" · "}
                    <strong className="priceAge--stale">
                      {noLivePriceCount} {noLivePriceCount === 1 ? "holding" : "holdings"} without a live price
                    </strong>{" "}
                    (statement or old quote) ·{" "}
                    <Link className="wealthInlineLink" to="/operations">
                      Fix in Data Hub
                    </Link>
                  </>
                ) : null}
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
                subtitle={summary?.is_live ? "Stock exposure · current" : `Stock exposure · ${summary?.as_of_month ?? month}`}
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

          {/* ── Geography performance (separate from allocation above) ──── */}
          <section aria-label="Stock geography performance">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">PERFORMANCE</p>
                <h2 className="coSectionTitle">Geography Performance</h2>
              </div>
              {geographyPerformanceAsOfLabel ? (
                <span className="muted" style={{ fontSize: "13px" }}>
                  Since {geographyPerformanceAsOfLabel}
                </span>
              ) : null}
            </div>
            <div className="card">
              {!summary?.is_live ? (
                <p className="muted">Geography performance is only available for the current, live period — pick the current month to see it.</p>
              ) : geographyPerformanceItems.length > 0 ? (
                <div className="coHoldingsList">
                  {geographyPerformanceItems.map((item) => (
                    <div key={item.geography} className="coHoldingRow">
                      <div className="coHoldingLeft">
                        <strong className="coHoldingSymbol">{formatGeoLabel(item.geography)}</strong>
                        <span className="coHoldingClass">{formatMoney(item.current_value)}</span>
                      </div>
                      <div className="coHoldingRight">
                        <strong className="coHoldingValue">
                          <Delta abs={item.delta_abs} compareValue={item.snapshot_value} currency={shownCurrency} show="abs" />
                        </strong>
                        <span className="coHoldingPct">
                          {fmt.formatPercent(deltaPercent(item.delta_abs, item.snapshot_value), { signed: true })}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No geography performance data yet.</p>
              )}
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
                {summary?.trend?.some((point) => point.is_live) ? " · MTD: this month to date, live" : ""}
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
              <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                <span className="muted" style={{ fontSize: "13px" }}>
                  {Math.min(visibleHoldings.length, holdings.length)} of {holdings.length} positions
                  {soldHoldings.length > 0 ? ` · ${soldHoldings.length} sold since ${compareLabel}` : ""}
                </span>
                <button
                  className="btn stockHoldingsRefreshBtn"
                  onClick={onRefresh}
                  disabled={refreshing || summary?.is_live === false}
                  title={summary?.is_live === false ? "Refresh only applies to the current month" : undefined}
                >
                  <span className={`stockHoldingsRefreshDot${refreshing ? " stockHoldingsRefreshDotActive" : ""}`} aria-hidden="true" />
                  {refreshing ? "Refreshing..." : "Refresh quotes"}
                </button>
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
              {isMobile ? (
                <div className="stockHoldingsMobileList">
                  {visibleHoldings.map((h, idx) => {
                    const sold = h.month_change?.side === "sold";
                    const mobilePnl = sold ? null : formatPnl(h);
                    const priceAge = holdingPriceAge(h, isLive);
                    return (
                      <article className="stockHoldingsMobileCard" key={`${sold ? "sold" : "held"}-${h.asset_id ?? `${h.symbol}-${idx}`}`}>
                        <div className="stockHoldingsMobileHeader">
                          <div>
                            <div className="stockHoldingsMobileTitleLine">
                              <strong className="stockHoldingsMobileTitle">{h.name ?? h.symbol}</strong>
                              <span className="stockHoldingsExchangePill">{formatExchangeLabel(h)}</span>
                            </div>
                            <div className="stockHoldingsMobileMeta">
                              {formatPlatformLabel(h.platform ?? "—")}{sold ? null : ` · ${formatGeoLabel(h.geo)}`}
                            </div>
                          </div>
                        </div>
                        {sold ? null : (
                        <div className="stockHoldingsMobileMetrics">
                          {isLive ? (
                            <span className={`stockHoldingsFreshnessTag stockHoldingsFreshnessTag${(h.quote_freshness_status ?? "").toLowerCase() === "fresh" ? "Fresh" : "Stale"}`}>
                              {formatFreshnessLabel(h.quote_freshness_status)}
                            </span>
                          ) : null}
                          {h.price_fallback_reason && (
                            <PriceFallbackInfo symbol={h.symbol} reason={h.price_fallback_reason} asOf={h.latest_trade_date} platform={h.platform} />
                          )}
                          <div className="stockHoldingsMobileValueBlock">
                            <strong>{formatMoney(h.value)}</strong>
                            <span>{fmt.formatPercent(h.percent_of_networth, { scale: "points" })} NW</span>
                          </div>
                          {mobilePnl ? (
                            <div className={`stockHoldingsMobilePnlBlock ${mobilePnl.positive ? "good" : "bad"}`} title={mobilePnl.native ?? undefined}>
                              <strong>{mobilePnl.amount}</strong>
                              {mobilePnl.pct == null ? null : <span>{fmt.formatPercent(mobilePnl.pct, { signed: true, scale: "points" })}</span>}
                            </div>
                          ) : null}
                        </div>
                        )}
                        {visibleColumns.monthChange ? (
                          <div className="stockHoldingsMobileChange">
                            <span className="muted">Since {compareLabel}</span>
                            <StockMonthChange
                              change={h.month_change}
                              currency={shownCurrency}
                              compareLabel={compareLabel}
                              symbol={h.symbol}
                              layout="card"
                            />
                          </div>
                        ) : null}
                        {sold ? null : (
                          <small className={`priceAge stockHoldingsMobilePriceAge${priceAge.stale ? " priceAge--stale" : ""}`}>
                            {priceAge.text}
                          </small>
                        )}
                      </article>
                    );
                  })}
                  {summary && rows.length === 0 && (
                    <p className="muted">No holdings available.</p>
                  )}
                </div>
              ) : (
                <div className="stockHoldingsTableWrap">
                  <table className="table stockHoldingsTable">
                    <thead>
                      <tr>
                        <th>Asset</th>
                        {visibleColumns.shares && <th className="right">Shares</th>}
                        {visibleColumns.purchasePrice && <th className="right">Purchase Price</th>}
                        {visibleColumns.currentPrice && <th className="right">Current Price</th>}
                        {visibleColumns.monthChange && <th className="right">Δ vs {compareLabel}</th>}
                        {visibleColumns.pnl && <th className="right">Profit &amp; Loss</th>}
                        {visibleColumns.percentNetWorth && <th className="right">% NW</th>}
                        {visibleColumns.quoteFreshness && <th>Quote freshness</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {visibleHoldings.map((h, idx) => {
                        const sold = h.month_change?.side === "sold";
                        const pnl = formatPnl(h);
                        const priceAge = holdingPriceAge(h, isLive);
                        if (sold) {
                          // #251: sold since the compare month-end: no price, P&L or weight now.
                          return (
                            <tr key={`sold-${h.asset_id ?? `${h.symbol}-${idx}`}`} className="stockHoldingsSoldRow">
                              <td>
                                <div className="stockHoldingsAssetCell">
                                  <div className="stockHoldingsSymbol">{h.symbol}</div>
                                  <div className="stockHoldingsAssetMeta">
                                    <span>{h.platform ? formatPlatformLabel(h.platform) : "—"}</span>
                                  </div>
                                </div>
                              </td>
                              {visibleColumns.shares && <td className="right stockHoldingsQuantityCell">{formatQuantity(0)}</td>}
                              {visibleColumns.purchasePrice && <td className="right muted">—</td>}
                              {visibleColumns.currentPrice && <td className="right muted">—</td>}
                              {visibleColumns.monthChange && (
                                <td className="right">
                                  <StockMonthChange change={h.month_change} currency={shownCurrency} compareLabel={compareLabel} symbol={h.symbol} />
                                </td>
                              )}
                              {visibleColumns.pnl && <td className="right muted">—</td>}
                              {visibleColumns.percentNetWorth && (
                                <td className="right stockHoldingsPercentCell">
                                  <small>{formatMoney(0)}</small>
                                </td>
                              )}
                              {visibleColumns.quoteFreshness && <td />}
                            </tr>
                          );
                        }
                        return (
                          <tr key={h.asset_id ?? `${h.symbol}-${idx}`}>
                            <td>
                              <div className="stockHoldingsAssetCell">
                                <div className="stockHoldingsSymbol">{h.symbol}</div>
                                <div className="stockHoldingsAssetMeta">
                                  <span>{h.platform ? formatPlatformLabel(h.platform) : "—"}</span>
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
                              <td className="right stockHoldingsPriceCell">
                                {formatNativeMoney(h.latest_price, h.quote_currency)}
                                {h.price_fallback_reason && (
                                  <PriceFallbackInfo symbol={h.symbol} reason={h.price_fallback_reason} asOf={h.latest_trade_date} platform={h.platform} />
                                )}
                              </td>
                            )}
                            {visibleColumns.monthChange && (
                              <td className="right">
                                <StockMonthChange change={h.month_change} currency={shownCurrency} compareLabel={compareLabel} symbol={h.symbol} />
                              </td>
                            )}
                            {visibleColumns.pnl && (
                              <td className={`right stockHoldingsPnlCell ${pnl.positive ? "good" : "bad"}`} title={pnl.native ?? undefined}>
                                <div>{pnl.amount}</div>
                                {pnl.pct == null ? null : <small>{fmt.formatPercent(pnl.pct, { signed: true, scale: "points" })}</small>}
                              </td>
                            )}
                            {visibleColumns.percentNetWorth && (
                              <td className="right stockHoldingsPercentCell">
                                <div>{fmt.formatPercent(h.percent_of_networth, { scale: "points" })}</div>
                                <small>{formatMoney(h.value)}</small>
                              </td>
                            )}
                            {visibleColumns.quoteFreshness && (
                              <td>
                                {isLive ? <div>{h.quote_freshness_status ?? "missing"}</div> : null}
                                <small className={`priceAge${priceAge.stale ? " priceAge--stale" : ""}`}>{priceAge.text}</small>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                      {summary && rows.length === 0 && (
                        <tr>
                          <td className="muted" colSpan={visibleColumnCount}>No holdings available.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              {rows.length > 0 ? (
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
                    onClick={() => setVisibleCount((current) => Math.min(rows.length, current + PAGE_SIZE))}
                    disabled={!hasMore}
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </div>
          </section>
        </RefreshingRegion>
      )}
    </PageShell>
  );
}
