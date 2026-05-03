import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DashboardSummary, SpendingSummary } from "../lib/api";
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
};

export default function WealthOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const selectedBaseCurrency = baseCurrency || summary?.base_currency || "SGD";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setState("loading");
        const [summaryData, spendingData] = await Promise.all([
          api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
          api.spendingSummary(month, baseCurrency),
        ]);
        if (cancelled) return;
        setSummary(summaryData);
        setSpendingSummary(spendingData);
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
  }, [month, baseCurrency]);

  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : selectedBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const netWorthTotal = summary?.net_worth.total ?? 0;
  const stocksPct = netWorthTotal ? ((summary?.net_worth.stocks_funds ?? 0) / netWorthTotal) * 100 : 0;
  const cryptoPct = netWorthTotal ? ((summary?.net_worth.crypto ?? 0) / netWorthTotal) * 100 : 0;
  const cashPct = netWorthTotal ? ((summary?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;

  const composition = useMemo<CompositionSlice[]>(
    () => [
      {
        label: "Stocks & Funds",
        percent: stocksPct,
        value: summary?.net_worth.stocks_funds ?? 0,
        to: "/holdings",
        toneClass: "wealthSliceStocks",
      },
      {
        label: "Crypto",
        percent: cryptoPct,
        value: summary?.net_worth.crypto ?? 0,
        to: "/crypto/holdings",
        toneClass: "wealthSliceCrypto",
      },
      {
        label: "Cash",
        percent: cashPct,
        value: summary?.net_worth.cash ?? 0,
        to: "/cash",
        toneClass: "wealthSliceCash",
      },
    ],
    [cashPct, cryptoPct, stocksPct, summary],
  );

  const topHoldings = (summary?.top_holdings ?? []).slice(0, 4);
  const prevMonthChange = summary?.net_worth_change?.vs_prev_month;
  const prevYearChange = summary?.net_worth_change?.vs_prev_year;

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
              <p className="wealthEyebrow">Consolidated Net Worth</p>
              <div className="wealthHeroValueRow">
                <h2 className="wealthHeroValue">{formatMoney(summary.net_worth.total, 2)}</h2>
                {prevMonthChange ? (
                  <span className={`wealthHeroChip ${prevMonthChange.abs >= 0 ? "wealthHeroChipPositive" : "wealthHeroChipNegative"}`}>
                    {prevMonthChange.abs >= 0 ? "+" : "-"}
                    {prevMonthChange.pct == null ? "—" : `${Math.abs(prevMonthChange.pct * 100).toFixed(1)}%`}
                  </span>
                ) : null}
              </div>
              <div className="wealthDeltaRow" aria-label="Net worth changes">
                {prevMonthChange ? renderDelta(`vs ${prevMonthChange.compare_month}`, prevMonthChange.abs, prevMonthChange.pct) : null}
                {prevYearChange ? renderDelta(`vs ${prevYearChange.compare_month}`, prevYearChange.abs, prevYearChange.pct) : null}
              </div>
            </article>

            <article className="card wealthAllocationCard">
              <div className="wealthAllocationHeader">
                <p className="wealthEyebrow">Portfolio Composition</p>
                <span className="wealthAllocationMeta">Percent of net worth</span>
              </div>
              <div className="wealthAllocationRail" aria-label="Net worth composition">
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
                <div className="wealthSurfaceFooter">
                  <span>{slice.percent.toFixed(1)}% of net worth</span>
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
          </section>
        </div>
      ) : null}
    </PageShell>
  );
}
