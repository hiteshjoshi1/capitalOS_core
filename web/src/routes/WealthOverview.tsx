import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DashboardSummary, SpendingSummary } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

type CompositionSlice = {
  label: string;
  percent: number;
  value: number;
  to: string;
  toneClass: string;
  deltaAbs?: number | null;
  deltaPct?: number | null;
  compareMonth?: string | null;
};

const PORTFOLIO_REFRESH_TOPIC = "portfolio-refresh";
const PORTFOLIO_REFRESH_DEBOUNCE_MS = 750;
const WEALTH_OVERVIEW_MONTH_STORAGE_KEY = "capitalos.selectedMonth.wealth";

export default function WealthOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [month, setMonth] = useSelectedMonth(WEALTH_OVERVIEW_MONTH_STORAGE_KEY);
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const selectedBaseCurrency = baseCurrency || summary?.base_currency || "SGD";

  const fetchDashboardData = useCallback(async () => {
    const [summaryData, spendingData] = await Promise.all([
      api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
      api.spendingSummary(month, baseCurrency),
    ]);
    return {
      summaryData,
      spendingData,
    };
  }, [baseCurrency, month]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setState("loading");
        setErr("");
        const data = await fetchDashboardData();
        if (cancelled) return;
        setSummary(data.summaryData);
        setSpendingSummary(data.spendingData);
        setState("ready");
      } catch (error: unknown) {
        if (cancelled) return;
        setErr(error instanceof Error ? error.message : String(error));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchDashboardData]);

  useEffect(() => {
    let cancelled = false;
    let refreshTimer: number | null = null;

    const refreshSummary = async () => {
      try {
        const data = await fetchDashboardData();
        if (cancelled) return;
        setSummary(data.summaryData);
        setSpendingSummary(data.spendingData);
        setErr("");
        setState("ready");
      } catch (error: unknown) {
        if (cancelled) return;
        setErr(error instanceof Error ? error.message : String(error));
        setState("error");
      }
    };

    const unsubscribe = subscribeToRealtimeTopic(PORTFOLIO_REFRESH_TOPIC, {
      onEvent: () => {
        if (refreshTimer != null) {
          window.clearTimeout(refreshTimer);
        }
        refreshTimer = window.setTimeout(() => {
          void refreshSummary();
        }, PORTFOLIO_REFRESH_DEBOUNCE_MS);
      },
    });

    return () => {
      cancelled = true;
      if (refreshTimer != null) {
        window.clearTimeout(refreshTimer);
      }
      unsubscribe();
    };
  }, [fetchDashboardData]);

  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : selectedBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatShortDate = (value?: string | null) => (value ? value.slice(0, 10) : "—");

  const currentNetWorth = summary?.current_net_worth ?? summary?.net_worth ?? null;
  const currentNetWorthAsOf = summary?.current_net_worth_as_of ?? summary?.net_worth_as_of ?? null;
  const currentFreshness = summary?.current_net_worth_freshness ?? null;
  const netWorthTotal = summary?.net_worth.total ?? 0;
  const stocksPct = netWorthTotal ? ((summary?.net_worth.stocks_funds ?? 0) / netWorthTotal) * 100 : 0;
  const cryptoPct = netWorthTotal ? ((summary?.net_worth.crypto ?? 0) / netWorthTotal) * 100 : 0;
  const cashPct = netWorthTotal ? ((summary?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;
  const currentFreshnessItems = useMemo(
    () => [
      { label: "Positions", value: currentFreshness?.positions_as_of ?? null },
      { label: "Prices", value: currentFreshness?.market_data_as_of ?? null },
      { label: "Crypto", value: currentFreshness?.crypto_as_of ?? null },
    ].filter((item): item is { label: string; value: string } => item.value != null),
    [currentFreshness],
  );

  const composition = useMemo<CompositionSlice[]>(
    () => [
      {
        label: "Stocks & Funds",
        percent: stocksPct,
        value: summary?.net_worth.stocks_funds ?? 0,
        to: "/holdings",
        toneClass: "wealthSliceStocks",
        deltaAbs: summary?.net_worth_component_change?.stocks_funds?.abs ?? null,
        deltaPct: summary?.net_worth_component_change?.stocks_funds?.pct ?? null,
        compareMonth: summary?.net_worth_component_change?.stocks_funds?.compare_month ?? null,
      },
      {
        label: "Crypto",
        percent: cryptoPct,
        value: summary?.net_worth.crypto ?? 0,
        to: "/crypto/holdings",
        toneClass: "wealthSliceCrypto",
        deltaAbs: summary?.net_worth_component_change?.crypto?.abs ?? null,
        deltaPct: summary?.net_worth_component_change?.crypto?.pct ?? null,
        compareMonth: summary?.net_worth_component_change?.crypto?.compare_month ?? null,
      },
      {
        label: "Cash",
        percent: cashPct,
        value: summary?.net_worth.cash ?? 0,
        to: "/cash",
        toneClass: "wealthSliceCash",
        deltaAbs: summary?.net_worth_component_change?.cash?.abs ?? null,
        deltaPct: summary?.net_worth_component_change?.cash?.pct ?? null,
        compareMonth: summary?.net_worth_component_change?.cash?.compare_month ?? null,
      },
    ],
    [cashPct, cryptoPct, stocksPct, summary],
  );

  const topHoldings = (summary?.top_holdings ?? []).slice(0, 4);
  const topMovers = summary?.top_movers ?? null;
  const prevMonthChange = summary?.net_worth_change?.vs_prev_month;
  const prevYearChange = summary?.net_worth_change?.vs_prev_year;
  const netWorthAsOf = summary?.net_worth_as_of ?? null;
  const snapshotCapturedAt = summary?.net_worth_snapshot_as_of ?? null;
  const snapshotFreshnessStatus = summary?.net_worth_freshness_status ?? "missing";
  const snapshotStatusLabel =
    snapshotFreshnessStatus === "exact"
      ? "Exact snapshot"
      : snapshotFreshnessStatus === "synthetic"
        ? "Synthetic snapshot"
        : "Snapshot missing";
  const snapshotStatusClass =
    snapshotFreshnessStatus === "exact"
      ? "wealthSnapshotBadgeExact"
      : snapshotFreshnessStatus === "synthetic"
        ? "wealthSnapshotBadgeSynthetic"
        : "wealthSnapshotBadgeMissing";

  const renderDelta = (label: string, abs: number, pct: number | null) => (
    <div className="wealthDeltaPill">
      <span className="wealthDeltaLabel">{label}</span>
      <strong className={abs >= 0 ? "wealthTrendPositive" : "wealthTrendNegative"}>
        {abs >= 0 ? "+" : "-"}
        {formatMoney(Math.abs(abs))}
        {pct == null ? "" : ` (${pct >= 0 ? "+" : "-"}${Math.abs(pct * 100).toFixed(1)}%)`}
      </strong>
    </div>
  );

  const renderMoverRow = (row: NonNullable<DashboardSummary["top_movers"]>["gainers"][number]) => (
    <div key={`${row.asset_class}-${row.symbol}`} className="wealthHoldingRow">
      <div>
        <strong>{row.symbol}</strong>
        <span className="muted wealthHoldingMeta">{row.asset_class}</span>
      </div>
      <div className="wealthHoldingValue">
        <strong className={row.delta_abs >= 0 ? "wealthTrendPositive" : "wealthTrendNegative"}>
          {row.delta_abs >= 0 ? "+" : "-"}
          {formatMoney(Math.abs(row.delta_abs))}
        </strong>
        <span className="muted">
          {row.delta_pct == null ? `vs ${row.compare_month}` : `${row.delta_pct >= 0 ? "+" : "-"}${Math.abs(row.delta_pct * 100).toFixed(1)}%`}
        </span>
      </div>
    </div>
  );

  return (
    <PageShell
      title="Wealth Overview"
      subtitle="Portfolio composition, monthly momentum, and the most important balance-sheet signals."
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
              aria-label="Base currency"
              value={selectedBaseCurrency}
              onChange={(event) => setBaseCurrency(event.target.value)}
            >
              <option value="SGD">SGD</option>
              <option value="USD">USD</option>
              <option value="HKD">HKD</option>
              <option value="INR">INR</option>
            </select>
          </label>
        </>
      )}
    >
      {state === "loading" ? <div className="card">Loading…</div> : null}
      {state === "error" ? (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      ) : null}

      {state === "ready" && summary ? (
        <div className="wealthOverviewLayout">
          <section className="wealthHeroGrid">
            <article className="card wealthHeroCard">
              <p className="wealthEyebrow">Current Net Worth</p>
              <div className="wealthHeroValueRow">
                <h2 className="wealthHeroValue">{formatMoney(currentNetWorth?.total, 2)}</h2>
                {prevMonthChange ? (
                  <span className={`wealthHeroChip ${prevMonthChange.abs >= 0 ? "wealthHeroChipPositive" : "wealthHeroChipNegative"}`}>
                    {prevMonthChange.abs >= 0 ? "+" : "-"}
                    {prevMonthChange.pct == null ? "—" : `${Math.abs(prevMonthChange.pct * 100).toFixed(1)}%`}
                  </span>
                ) : null}
              </div>
              <p className="muted wealthAsOfLine">
                Current net worth as of {formatShortDate(currentNetWorthAsOf)}
              </p>
              {currentFreshnessItems.length > 0 ? (
                <div className="wealthFreshnessRow" aria-label="Current data freshness">
                  {currentFreshnessItems.map((item) => (
                    <div key={item.label} className="wealthFreshnessPill">
                      <span className="wealthFreshnessLabel">{item.label}</span>
                      <strong>{formatShortDate(item.value)}</strong>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="wealthSnapshotPanel">
                <div className="wealthSnapshotPanelHeader">
                  <div>
                    <p className="wealthSnapshotLabel">Snapshot net worth for {month}</p>
                    <strong className="wealthSnapshotValue">{formatMoney(summary.net_worth.total, 2)}</strong>
                  </div>
                  <span className={`wealthSnapshotBadge ${snapshotStatusClass}`}>{snapshotStatusLabel}</span>
                </div>
                <p className="muted wealthSnapshotMeta">
                  {`Snapshot day ${summary.snapshot_day ?? "—"} · Captured ${formatShortDate(snapshotCapturedAt)} · Boundary ${formatShortDate(netWorthAsOf)}`}
                </p>
              </div>
              <div className="wealthDeltaRow" aria-label="Net worth changes">
                {prevMonthChange ? renderDelta(`vs ${prevMonthChange.compare_month}`, prevMonthChange.abs, prevMonthChange.pct) : null}
                {prevYearChange ? renderDelta(`vs ${prevYearChange.compare_month}`, prevYearChange.abs, prevYearChange.pct) : null}
              </div>
            </article>

            <article className="card wealthAllocationCard">
              <div className="wealthAllocationHeader">
                <p className="wealthEyebrow">Portfolio Composition</p>
                <span className="wealthAllocationMeta">Percent of snapshot net worth</span>
              </div>
              <div className="wealthAllocationRail" aria-label="Snapshot net worth composition">
                {composition.map((slice) => (
                  <span
                    key={slice.label}
                    className={`wealthAllocationSegment ${slice.toneClass}`}
                    style={{ width: `${slice.percent}%` }}
                  />
                ))}
              </div>
              <div className="wealthCompositionGrid">
                {composition.map((slice) => (
                  <Link
                    key={slice.label}
                    aria-label={`${slice.label} composition`}
                    className="wealthCompositionItem"
                    to={slice.to}
                  >
                    <span className={`wealthCompositionDot ${slice.toneClass}`} aria-hidden="true" />
                    <span className="wealthCompositionLabel">{slice.label}</span>
                    <strong>{slice.percent.toFixed(1)}%</strong>
                    <small>{formatMoney(slice.value)}</small>
                  </Link>
                ))}
              </div>
            </article>
          </section>

          <section className="wealthSurfaceGrid">
            {composition.map((slice) => (
              <Link
                key={slice.label}
                aria-label={`${slice.label} details`}
                className="card wealthSurfaceCard"
                to={slice.to}
              >
                <p className="wealthEyebrow">{slice.label}</p>
                <h2 className="wealthSurfaceValue">{formatMoney(slice.value)}</h2>
                {slice.deltaAbs != null && slice.compareMonth ? (
                  <p className="wealthSurfaceDelta">
                    <span className={slice.deltaAbs >= 0 ? "wealthTrendPositive" : "wealthTrendNegative"}>
                      {slice.deltaAbs >= 0 ? "+" : "-"}
                      {formatMoney(Math.abs(slice.deltaAbs))}
                      {slice.deltaPct == null ? "" : ` (${slice.deltaPct >= 0 ? "+" : "-"}${Math.abs(slice.deltaPct * 100).toFixed(1)}%)`}
                    </span>
                    {` vs ${slice.compareMonth}`}
                  </p>
                ) : null}
                <div className="wealthSurfaceFooter">
                  <span>{slice.percent.toFixed(1)}% of snapshot net worth</span>
                  <span>Open details</span>
                </div>
              </Link>
            ))}
          </section>

          <section className="wealthDetailGrid">
            <article className="card wealthDetailCard">
              <p className="wealthEyebrow">Cash Flow</p>
              <h2 className="wealthDetailTitle">{formatMoney(spendingSummary?.net)}</h2>
              <p className="muted">
                Income {formatMoney(spendingSummary?.income_total)} · Expenses {formatMoney(spendingSummary?.expense_total)} · Saved {spendingSummary?.savings_rate == null ? "—" : `${(spendingSummary.savings_rate * 100).toFixed(1)}%`}
              </p>
              <Link className="wealthInlineLink" to="/cash-flow">Open cash flow workspace</Link>
            </article>

            <article className="card wealthDetailCard">
              <p className="wealthEyebrow">Liabilities</p>
              <h2 className="wealthDetailTitle">{formatMoney(summary.net_worth.liabilities)}</h2>
              <p className="muted">Outstanding obligations remain visible inside the Liabilities section overview.</p>
              <Link className="wealthInlineLink" to="/liabilities">Open liabilities</Link>
            </article>

            <article className="card wealthDetailCard wealthDetailCardWide">
              <div className="wealthDetailSplit">
                <div>
                  <p className="wealthEyebrow">Top Holdings</p>
                  <h2 className="wealthDetailTitle">Largest positions</h2>
                </div>
                <Link className="wealthInlineLink" to="/risk">Open risk view</Link>
              </div>
              <div className="wealthHoldingsList">
                {topHoldings.length > 0 ? (
                  topHoldings.map((holding) => (
                    <div key={holding.asset_id ?? holding.symbol} className="wealthHoldingRow">
                      <div>
                        <strong>{holding.symbol}</strong>
                        <span className="muted wealthHoldingMeta">{holding.asset_class}</span>
                      </div>
                      <div className="wealthHoldingValue">
                        <strong>{formatMoney(holding.value)}</strong>
                        <span className="muted">{holding.percent_of_networth.toFixed(1)}%</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="muted">No holdings were returned for this month.</p>
                )}
              </div>
            </article>

            <article className="card wealthDetailCard wealthDetailCardWide">
              <div className="wealthDetailSplit">
                <div>
                  <p className="wealthEyebrow">Top Movers</p>
                  <h2 className="wealthDetailTitle">Gainers & detractors</h2>
                </div>
                {topMovers ? <span className="muted">{`vs ${topMovers.compare_month}`}</span> : null}
              </div>
              <div className="wealthMoversGrid">
                <div className="wealthMoversColumn wealthMoversColumnPositive">
                  <div className="wealthMoverSectionHeader">
                    <p className="wealthMoverSectionLabel">Top gainers</p>
                    <span className="wealthMoverBadge wealthMoverBadgePositive">Up</span>
                  </div>
                  <div className="wealthHoldingsList">
                    {topMovers?.gainers?.length ? topMovers.gainers.map(renderMoverRow) : <p className="muted">No positive movers for this period.</p>}
                  </div>
                </div>
                <div className="wealthMoversColumn wealthMoversColumnNegative">
                  <div className="wealthMoverSectionHeader">
                    <p className="wealthMoverSectionLabel">Top detractors</p>
                    <span className="wealthMoverBadge wealthMoverBadgeNegative">Down</span>
                  </div>
                  <div className="wealthHoldingsList">
                    {topMovers?.detractors?.length ? topMovers.detractors.map(renderMoverRow) : <p className="muted">No negative movers for this period.</p>}
                  </div>
                </div>
              </div>
            </article>

          </section>
        </div>
      ) : null}
    </PageShell>
  );
}
