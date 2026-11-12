import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DividendCompanyItem, StockHolding, StockPlatformTotal } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { monthEndCloseDate, shiftMonth, snapshotMonthOf, useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import { deltaDirection, deltaPercent, noDataFor } from "../lib/delta";
import { hasLivePrice, holdingPriceAge } from "../lib/priceAge";
import { holdingPnlBase } from "../lib/holdingPnl";
import "../App.css";
import Delta, { DeltaArrow } from "../components/Delta";
import ExposurePieCard from "../components/ExposurePieCard";
import MonthBar from "../components/MonthBar";
import PriceFallbackInfo from "../components/PriceFallbackInfo";
import StockMonthChange from "../components/StockMonthChange";
import RealisedPnlCard from "../components/RealisedPnlCard";
import PageShell from "../components/PageShell";
import ValueTrendChart from "../components/ValueTrendChart";
import { useBaseCurrency } from "../context/CurrencyContext";
import LoadError from "../components/LoadError";

/** P&L colour by direction (#268): zero is neutral, not green. */
const PNL_CLASS = { up: "good", down: "bad", flat: "" } as const;

type StockColumnKey = "shares" | "purchasePrice" | "currentPrice" | "monthChange" | "pnl" | "percentNetWorth" | "dividends" | "quoteFreshness";

/** #396 (U6): the page's job is the full list; it pages only above this many rows. */
const PAGE_SIZE = 100;

/** #396 (U5): what the holdings are sorted by. "weight" is the API's order (value, largest first). */
type SortKey = "weight" | "change" | "pnl" | "name";
const SORT_OPTIONS: Array<{ key: SortKey; label: string }> = [
  { key: "weight", label: "Weight" },
  { key: "change", label: "Change vs month-end" },
  { key: "pnl", label: "Profit & Loss" },
  { key: "name", label: "Name" },
];
const MOBILE_BREAKPOINT_PX = 900;
// v2 (#418): Quote freshness moved off by default so the table fits at 1440px; a new key so a
// saved choice from before (all columns on) doesn't keep the table too wide.
const STOCK_COLUMN_STORAGE_KEY = "capitalos.stockHoldings.visibleColumns.v2";
const STOCK_COLUMN_OPTIONS: Array<{ key: StockColumnKey; label: string; align?: "right" }> = [
  { key: "shares", label: "Shares", align: "right" },
  { key: "purchasePrice", label: "Purchase Price", align: "right" },
  { key: "currentPrice", label: "Current Price", align: "right" },
  { key: "monthChange", label: "Change vs month-end", align: "right" },
  { key: "pnl", label: "Profit & Loss", align: "right" },
  { key: "percentNetWorth", label: "% NW", align: "right" },
  { key: "dividends", label: "Dividends", align: "right" },
  { key: "quoteFreshness", label: "Quote freshness" },
];
const DEFAULT_VISIBLE_STOCK_COLUMNS: Record<StockColumnKey, boolean> = {
  shares: true,
  purchasePrice: true,
  currentPrice: true,
  monthChange: true,
  pnl: true,
  percentNetWorth: true,
  dividends: true,
  // #418: in the Columns picker; with it off, a stale price is still flagged in the Current Price cell.
  quoteFreshness: false,
};

/** Dividends paid on a holding: matched by asset id, else by symbol (#396, U8). */
function dividendFor(items: DividendCompanyItem[] | undefined, holding: StockHolding): DividendCompanyItem | undefined {
  if (!items) return undefined;
  return items.find((item) => holding.asset_id != null && item.asset_id === holding.asset_id)
    ?? items.find((item) => item.asset_id == null && item.symbol != null && item.symbol.toUpperCase() === holding.symbol.toUpperCase());
}

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
  const [sortKey, setSortKey] = useState<SortKey>("weight");
  const [sortDesc, setSortDesc] = useState<boolean>(true);
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

  // #396 (U8): dividends per holding, only while the column is shown. "This year" is the
  // selected month's calendar year to date; the yield is the last 12 months' dividends over
  // the holding's value now (as on Income).
  const [dividends, setDividends] = useState<{ key: string; ytd: DividendCompanyItem[]; trailing: DividendCompanyItem[] } | null>(null);
  const dividendsKey = `${month}|${baseCurrency}`;
  const showDividends = visibleColumns.dividends;
  useEffect(() => {
    if (!showDividends) return;
    let cancelled = false;
    const year = month.slice(0, 4);
    Promise.all([
      api.dividendsByCompany(`${year}-01`, month, baseCurrency),
      api.dividendsByCompany(shiftMonth(month, -11), month, baseCurrency),
    ])
      .then(([ytd, trailing]) => {
        if (!cancelled) setDividends({ key: dividendsKey, ytd: ytd.items, trailing: trailing.items });
      })
      // The column then shows "—": dividends are a side panel, not the page.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [showDividends, month, baseCurrency, dividendsKey]);
  const shownDividends = dividends && dividends.key === dividendsKey ? dividends : null;

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDesc((current) => !current);
    } else {
      setSortKey(key);
      setSortDesc(key !== "name");
    }
    setVisibleCount(PAGE_SIZE);
  };

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
  const formatMoney = (value?: number | null, decimals?: number) => fmt.formatMoney(value, shownCurrency, { decimals });
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
      return { amount: "—", native: null, pct: null, positive: true, direction: "flat" as const };
    }
    const nativePnl = holding.quantity * (holding.latest_price - holding.avg_cost);
    const native = fmt.formatSignedMoney(nativePnl, holding.quote_currency, { decimals: 2 });
    const pnlPct = holding.avg_cost > 0 ? ((holding.latest_price - holding.avg_cost) / holding.avg_cost) * 100 : null;
    const nativeValue = holding.quantity * holding.latest_price;
    if (nativeValue <= 0 || holding.value == null) {
      return { amount: native, native: null, pct: pnlPct, positive: nativePnl >= 0, direction: deltaDirection(nativePnl) };
    }
    const pnl = nativePnl * (holding.value / nativeValue);
    return {
      amount: fmt.formatSignedMoney(pnl, shownCurrency),
      native: holding.quote_currency.toUpperCase() === shownCurrency.toUpperCase() ? null : `In ${holding.quote_currency}: ${native}`,
      pct: pnlPct,
      positive: pnl >= 0,
      direction: deltaDirection(pnl),
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
  // #396 (U5): sorted by the chosen column. Sold holdings have a change but no P&L or
  // weight, so they sort in only by change; otherwise they stay after the held ones.
  const rows = useMemo(() => {
    const dir = sortDesc ? -1 : 1;
    const byNumber = (a: number | null | undefined, b: number | null | undefined) => {
      if (a == null && b == null) return 0;
      if (a == null) return 1;
      if (b == null) return -1;
      return (a - b) * dir;
    };
    if (sortKey === "change") {
      return [...holdings, ...soldHoldings].sort((a, b) => byNumber(a.month_change?.abs, b.month_change?.abs));
    }
    const held = [...holdings];
    if (sortKey === "pnl") held.sort((a, b) => byNumber(holdingPnlBase(a), holdingPnlBase(b)));
    else if (sortKey === "name") held.sort((a, b) => (a.name ?? a.symbol).localeCompare(b.name ?? b.symbol) * dir);
    else if (!sortDesc) held.reverse();
    return [...held, ...soldHoldings];
  }, [holdings, soldHoldings, sortKey, sortDesc]);
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
          fmt.formatCsvNumber(pnl),
          fmt.formatCsvNumber(pnlPct),
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
  const paged = rows.length > PAGE_SIZE;
  const platformTotals: StockPlatformTotal[] = summary?.platform_totals ?? [];
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
  // #396 (U4): each geography's change on the page's own baseline (the compare
  // month-end, like the header), for any month, not a separate "since last update".
  const geographyChangeItems = useMemo(
    () => (summary?.geography_breakdown ?? [])
      .filter((item) => item.current_value > 0 || item.snapshot_value > 0)
      .sort((a, b) => b.current_value - a.current_value),
    [summary?.geography_breakdown],
  );

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
        </>
      }
      monthBar={<MonthBar month={month} onMonthChange={handleMonthChange} />}
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

          {/* ── Realised P&L on sales (#293) ──────────────────────────── */}
          <RealisedPnlCard month={month} baseCurrency={baseCurrency} />

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

          {/* ── Change by geography, on the page's baseline (#396, U4) ── */}
          <section aria-label="Stock change by geography">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">PERFORMANCE</p>
                <h2 className="coSectionTitle">Change by geography</h2>
              </div>
              <span className="muted" style={{ fontSize: "13px" }}>vs {compareLabel}</span>
            </div>
            <div className="card">
              {stockMissingReason ? (
                <p className="muted">{stockMissingReason}</p>
              ) : geographyChangeItems.length > 0 ? (
                <div className="coHoldingsList">
                  {geographyChangeItems.map((item) => (
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
                <p className="muted">No stocks in this month or the one it's compared with.</p>
              )}
            </div>
          </section>

          {/* ── Cost and unrealised P&L per platform (#396, U7) ──────── */}
          {platformTotals.length > 0 ? (
            <section aria-label="Stocks by platform">
              <div className="coSectionHeader">
                <div>
                  <p className="coEyebrow">BY PLATFORM</p>
                  <h2 className="coSectionTitle">Cost and unrealised profit</h2>
                </div>
              </div>
              <div className="card">
                <div className="coHoldingsList stockPlatformTotals">
                  {platformTotals.map((item) => {
                    const direction = deltaDirection(item.unrealised_pnl);
                    return (
                      <div key={item.platform} className="coHoldingRow" data-testid={`platform-total-${item.platform}`}>
                        <div className="coHoldingLeft">
                          <strong className="coHoldingSymbol">{formatPlatformLabel(item.platform)}</strong>
                          <span className="coHoldingClass">
                            {formatMoney(item.value)} now · cost {formatMoney(item.cost_basis)}
                            {" · "}{item.positions} {item.positions === 1 ? "position" : "positions"}
                          </span>
                          {item.positions_without_cost > 0 ? (
                            <span className="coHoldingClass muted">
                              {item.positions_without_cost} without a purchase price ({formatMoney(item.value_without_cost)}) left out of cost and profit
                            </span>
                          ) : null}
                        </div>
                        <div className="coHoldingRight">
                          <strong className={`coHoldingValue ${PNL_CLASS[direction]}`}>
                            <DeltaArrow direction={direction} />{fmt.formatSignedMoney(item.unrealised_pnl, shownCurrency)}
                          </strong>
                          <span className="coHoldingPct">
                            {item.unrealised_pnl_pct == null ? fmt.MISSING : fmt.formatPercent(item.unrealised_pnl_pct, { signed: true, scale: "points" })}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          ) : null}

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
                  {paged ? `${Math.min(visibleHoldings.length, holdings.length)} of ` : ""}{holdings.length} {holdings.length === 1 ? "position" : "positions"}
                  {soldHoldings.length > 0 ? ` · ${soldHoldings.length} sold since ${compareLabel}` : ""}
                </span>
                <label className="stockSortControl">
                  <span>Sort</span>
                  <select value={sortKey} onChange={(event) => handleSort(event.target.value as SortKey)} aria-label="Sort holdings by">
                    {SORT_OPTIONS.map((option) => (
                      <option key={option.key} value={option.key}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="btn stockSortDirection"
                  onClick={() => setSortDesc((current) => !current)}
                  aria-label={sortDesc ? "Sorted high to low; sort low to high" : "Sorted low to high; sort high to low"}
                  title={sortDesc ? "High to low" : "Low to high"}
                >
                  {sortDesc ? "↓" : "↑"}
                </button>
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
                  <div className="stockColumnPanel" role="group" aria-label="Visible stock columns">
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
                            <div className={`stockHoldingsMobilePnlBlock ${PNL_CLASS[mobilePnl.direction]}`} title={mobilePnl.native ?? undefined}>
                              <strong><DeltaArrow direction={mobilePnl.direction} />{mobilePnl.amount}</strong>
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
                        {!sold && visibleColumns.dividends ? (
                          <DividendsLine holding={h} dividends={shownDividends} currency={shownCurrency} layout="card" />
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
                        {visibleColumns.monthChange && (
                          <SortHeader label={`Δ vs ${compareLabel}`} sortKey="change" current={sortKey} desc={sortDesc} onSort={handleSort} />
                        )}
                        {visibleColumns.pnl && <SortHeader label="Profit & Loss" sortKey="pnl" current={sortKey} desc={sortDesc} onSort={handleSort} />}
                        {visibleColumns.percentNetWorth && <SortHeader label="% NW" sortKey="weight" current={sortKey} desc={sortDesc} onSort={handleSort} />}
                        {visibleColumns.dividends && <th className="right">Dividends</th>}
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
                              {visibleColumns.dividends && <td />}
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
                                {/* #418: Quote freshness is off by default; a stale price must still show. */}
                                {!visibleColumns.quoteFreshness && priceAge.stale ? (
                                  <small className="priceAge priceAge--stale stockHoldingsPriceAge">{priceAge.text}</small>
                                ) : null}
                              </td>
                            )}
                            {visibleColumns.monthChange && (
                              <td className="right">
                                <StockMonthChange change={h.month_change} currency={shownCurrency} compareLabel={compareLabel} symbol={h.symbol} />
                              </td>
                            )}
                            {visibleColumns.pnl && (
                              <td className={`right stockHoldingsPnlCell ${PNL_CLASS[pnl.direction]}`} title={pnl.native ?? undefined}>
                                <div><DeltaArrow direction={pnl.direction} />{pnl.amount}</div>
                                {pnl.pct == null ? null : <small>{fmt.formatPercent(pnl.pct, { signed: true, scale: "points" })}</small>}
                              </td>
                            )}
                            {visibleColumns.percentNetWorth && (
                              <td className="right stockHoldingsPercentCell">
                                <div>{fmt.formatPercent(h.percent_of_networth, { scale: "points" })}</div>
                                <small>{formatMoney(h.value)}</small>
                              </td>
                            )}
                            {visibleColumns.dividends && (
                              <td className="right">
                                <DividendsLine holding={h} dividends={shownDividends} currency={shownCurrency} layout="cell" />
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
              {paged ? (
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

/** A sortable column header (#396, U5): a button, with aria-sort on the active one. */
function SortHeader({ label, sortKey, current, desc, onSort }: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  desc: boolean;
  onSort: (key: SortKey) => void;
}) {
  const active = current === sortKey;
  return (
    <th className="right" aria-sort={active ? (desc ? "descending" : "ascending") : "none"}>
      <button type="button" className="stockSortHeader" onClick={() => onSort(sortKey)}>
        {label}
        <span aria-hidden="true">{active ? (desc ? " ↓" : " ↑") : ""}</span>
      </button>
    </th>
  );
}

/** Dividends paid this year and the trailing 12-month yield, linking to Income (#396, U8). */
function DividendsLine({ holding, dividends, currency, layout }: {
  holding: StockHolding;
  dividends: { ytd: DividendCompanyItem[]; trailing: DividendCompanyItem[] } | null;
  currency: string;
  layout: "cell" | "card";
}) {
  if (!dividends) return <span className="muted">{fmt.MISSING}</span>;
  const ytd = dividendFor(dividends.ytd, holding);
  const trailing = dividendFor(dividends.trailing, holding);
  if (!ytd?.gross && !trailing?.gross) {
    return layout === "card" ? null : <span className="muted">None</span>;
  }
  const yieldText = trailing?.yield_pct != null ? `${fmt.formatPercent(trailing.yield_pct, { scale: "points" })} yield` : null;
  return (
    <Link className={`stockDividends stockDividends--${layout}`} to="/income" title="Dividends this year, and the last 12 months' over the value now">
      <span>{fmt.formatMoney(ytd?.gross ?? 0, currency)} this year</span>
      {yieldText ? <small>{yieldText}</small> : null}
    </Link>
  );
}
