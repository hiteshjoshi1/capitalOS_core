import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CashFlowTrendPoint, DividendSummaryBucket, FxStatus, WealthTimeline } from "../lib/api";
import PageShell from "../components/PageShell";
import FxNote from "../components/FxNote";
import WealthHistoryChart, { type WealthHistoryChartMode } from "../components/WealthHistoryChart";
import WealthAttributionStrip from "../components/WealthAttributionStrip";
import WealthDrilldownPanel from "../components/WealthDrilldownPanel";
import { computeMonthFlags, isGapPoint } from "../lib/wealthHistoryAnalysis";
import "../App.css";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import MonthControl from "../components/MonthControl";
import * as fmt from "../lib/format";
import { shiftMonth, useSelectedMonth } from "../lib/selectedMonth";
import LoadError from "../components/LoadError";

type LoadState = "loading" | "ready" | "error";

const RANGE_OPTIONS: { label: string; months: number }[] = [
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "2Y", months: 24 },
  { label: "All", months: 60 },
];

function currentMonth(): string {
  return fmt.currentMonth();
}

function monthsBetween(from: string, to: string): number {
  const [fy, fm] = from.split("-").map(Number);
  const [ty, tm] = to.split("-").map(Number);
  return (ty - fy) * 12 + (tm - fm);
}

/** `range`, widened to the smallest range option that reaches back to `month` (#223), so a
 * selected month older than the range is still on the chart. Never narrowed. */
function rangeCovering(month: string, range: number): number {
  const needed = monthsBetween(month, currentMonth()) + 1;
  if (needed <= range) return range;
  return RANGE_OPTIONS.find((opt) => opt.months >= needed)?.months ?? RANGE_OPTIONS[RANGE_OPTIONS.length - 1].months;
}

function monthLabel(month: string): string {
  return fmt.formatMonth(month, "short");
}

export default function WealthHistory() {
  // #223: the shared selected month (the pill every page shows). It is marked on the chart
  // and opens its drill-down; picking a month on the chart sets it for every page.
  const [selectedMonth, setSelectedMonth] = useSelectedMonth();
  const [drilldownOpen, setDrilldownOpen] = useState(true);
  const [range, setRange] = useState<number>(() => rangeCovering(selectedMonth, 24));
  const [mode, setMode] = useState<WealthHistoryChartMode>("total");
  const [baseCurrency] = useBaseCurrency();

  // Everything starts loading: the fetch effects below only set state once a response arrives.
  const [timelineState, setTimelineState] = useState<LoadState>("loading");
  const [timelineErr, setTimelineErr] = useState("");
  const [timeline, setTimeline] = useState<WealthTimeline | null>(null);
  const [timelineReload, setTimelineReload] = useState(0);
  const [backfilling, setBackfilling] = useState(false);

  const [dividendsState, setDividendsState] = useState<LoadState>("loading");
  const [dividendBuckets, setDividendBuckets] = useState<DividendSummaryBucket[]>([]);

  const [cashFlowState, setCashFlowState] = useState<LoadState>("loading");
  const [cashFlowTrend, setCashFlowTrend] = useState<CashFlowTrendPoint[]>([]);
  const [cashFlowFx, setCashFlowFx] = useState<FxStatus | null>(null);

  // Range/currency changes refetch everything (back to loading); a currency change closes the
  // drill-down (its figures were in the other currency). A new selected month opens its
  // drill-down and widens the range to reach it. Adjusted while rendering, not in an effect,
  // so no stale frame is committed.
  const [prevInputs, setPrevInputs] = useState({ range, baseCurrency, selectedMonth });
  if (
    prevInputs.range !== range ||
    prevInputs.baseCurrency !== baseCurrency ||
    prevInputs.selectedMonth !== selectedMonth
  ) {
    const nextRange = prevInputs.selectedMonth !== selectedMonth ? rangeCovering(selectedMonth, range) : range;
    setPrevInputs({ range: nextRange, baseCurrency, selectedMonth });
    if (nextRange !== range) setRange(nextRange);
    if (prevInputs.range !== nextRange || prevInputs.baseCurrency !== baseCurrency) {
      setTimelineState("loading");
      setDividendsState("loading");
      setCashFlowState("loading");
    }
    if (prevInputs.selectedMonth !== selectedMonth) setDrilldownOpen(true);
    else if (prevInputs.baseCurrency !== baseCurrency) setDrilldownOpen(false);
  }

  const selectMonth = useCallback(
    (month: string) => {
      setSelectedMonth(month);
      setDrilldownOpen(true);
    },
    [setSelectedMonth],
  );

  // `ignore` drops a response that a newer request (or unmount) has superseded.
  useEffect(() => {
    let ignore = false;
    void (async () => {
      try {
        const data = await api.netWorthTimeline(range, baseCurrency);
        if (ignore) return;
        setTimeline(data);
        setTimelineState("ready");
      } catch (error: unknown) {
        if (ignore) return;
        setTimelineErr(error instanceof Error ? error.message : String(error));
        setTimelineState("error");
      }
    })();
    return () => {
      ignore = true;
    };
  }, [range, baseCurrency, timelineReload]);

  useEffect(() => {
    let ignore = false;
    void (async () => {
      try {
        const fromMonth = shiftMonth(currentMonth(), -(range - 1));
        const data = await api.dividendsSummary(fromMonth, currentMonth(), "month", baseCurrency);
        if (ignore) return;
        setDividendBuckets(data.buckets);
        setDividendsState("ready");
      } catch {
        if (!ignore) setDividendsState("error");
      }
    })();
    void (async () => {
      try {
        const data = await api.cashFlowDetail(currentMonth(), baseCurrency);
        if (ignore) return;
        setCashFlowTrend(data.analytics.trend);
        setCashFlowFx(data);
        setCashFlowState("ready");
      } catch {
        if (!ignore) setCashFlowState("error");
      }
    })();
    return () => {
      ignore = true;
    };
  }, [range, baseCurrency]);

  const handleGenerateHistory = useCallback(async () => {
    setBackfilling(true);
    try {
      await api.netWorthTimelineBackfill(range, baseCurrency);
      // Refetch the timeline through the effect above.
      setTimelineState("loading");
      setTimelineReload((n) => n + 1);
    } finally {
      setBackfilling(false);
    }
  }, [range, baseCurrency]);

  const formatMoney = useCallback(
    (value?: number | null, decimals = 0) => fmt.formatMoney(value, baseCurrency, { decimals }),
    [baseCurrency],
  );
  const formatMoneyShort = useCallback((value?: number | null) => fmt.formatMoneyCompact(value, baseCurrency), [baseCurrency]);

  const hasAnyData = useMemo(() => (timeline ? timeline.points.some((p) => !isGapPoint(p)) : false), [timeline]);

  const monthFlags = useMemo(() => computeMonthFlags(timeline?.points ?? []), [timeline]);
  // The open month has no stored row (it is the "now" point), so it has no drill-down.
  const selectedPoint = useMemo(
    () => (drilldownOpen ? (timeline?.points.find((p) => p.month === selectedMonth) ?? null) : null),
    [timeline, selectedMonth, drilldownOpen],
  );
  const selectedFlags = selectedPoint ? monthFlags.get(selectedPoint.month) : null;
  const selectedPrevPoint = useMemo(() => {
    if (!selectedFlags?.comparedToMonth) return null;
    return timeline?.points.find((p) => p.month === selectedFlags.comparedToMonth) ?? null;
  }, [timeline, selectedFlags]);

  const dividendMax = useMemo(
    () => Math.max(1, ...dividendBuckets.map((b) => b.net_received)),
    [dividendBuckets],
  );
  const ttmDividends = useMemo(
    () => dividendBuckets.slice(-12).reduce((acc, b) => acc + b.net_received, 0),
    [dividendBuckets],
  );

  const cashFlowMax = useMemo(
    () => Math.max(1, ...cashFlowTrend.flatMap((p) => [p.inflows, p.outflows])),
    [cashFlowTrend],
  );

  return (
    <PageShell
      title="History"
      subtitle="How your wealth evolved — and why. Carried data is shown dashed; gaps stay gaps."
      headerActions={
        <>
          <MonthControl month={selectedMonth} onMonthChange={setSelectedMonth} />
          <BaseCurrencyPicker />
        </>
      }
    >
      <div className="whFilters">
        <div className="coSegmentedControl" role="group" aria-label="Range">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              type="button"
              className={`coSegmentedBtn${range === opt.months ? " coSegmentedBtnActive" : ""}`}
              onClick={() => setRange(opt.months)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="coSegmentedControl" role="group" aria-label="Series mode">
          <button
            type="button"
            className={`coSegmentedBtn${mode === "total" ? " coSegmentedBtnActive" : ""}`}
            onClick={() => setMode("total")}
          >
            Total
          </button>
          <button
            type="button"
            className={`coSegmentedBtn${mode === "comp" ? " coSegmentedBtnActive" : ""}`}
            onClick={() => setMode("comp")}
          >
            By component
          </button>
        </div>
      </div>

      {timelineState === "loading" ? <div className="card" role="status">Loading…</div> : null}
      {timelineState === "error" ? (
        <LoadError title="Couldn't load history" error={timelineErr} onRetry={() => setTimelineReload((n) => n + 1)} />
      ) : null}

      {timelineState === "ready" && timeline ? (
        !hasAnyData ? (
          <div className="card whEmptyState">
            <p className="cardTitle">No history yet</p>
            <p className="muted">
              Generate the timeline from your existing statements and snapshots. This can be re-run any time — it's
              always safe to repeat.
            </p>
            <button type="button" className="btn" onClick={() => void handleGenerateHistory()} disabled={backfilling}>
              {backfilling ? "Generating…" : "Generate history"}
            </button>
          </div>
        ) : (
          <div className="whLayout">
          <div className="whLayoutMain">
            <div className="whCard">
              <div className="whCardHead">
                <div>
                  <div className="whCardTitle">Net worth</div>
                  <div className="whCardMeta">
                    {monthLabel(timeline.points[0]?.month ?? "")} – {monthLabel(timeline.points[timeline.points.length - 1]?.month ?? "")}{" "}
                    · monthly snapshots · {baseCurrency}
                  </div>
                </div>
                <button
                  type="button"
                  className="whRefreshBtn"
                  onClick={() => void handleGenerateHistory()}
                  disabled={backfilling}
                  title="Recompute this range from the latest data"
                >
                  {backfilling ? "Refreshing…" : "Refresh"}
                </button>
              </div>
              <WealthHistoryChart
                points={timeline.points}
                now={timeline.now}
                mode={mode}
                formatMoney={formatMoney}
                formatMoneyShort={formatMoneyShort}
                selectedMonth={selectedMonth}
                onSelectMonth={selectMonth}
              />

              <div className="whAttribDivider" />
              <WealthAttributionStrip
                points={timeline.points}
                formatMoney={formatMoney}
                selectedMonth={selectedMonth}
                onSelectMonth={selectMonth}
              />

              <details className="whTableView">
                <summary>View as table</summary>
                <div className="whTableScroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Month</th>
                        <th>Total</th>
                        <th>Stocks</th>
                        <th>Cash</th>
                        <th>Crypto</th>
                        <th>Liabilities</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {timeline.points.map((p) => (
                        <tr key={p.month}>
                          <td>{monthLabel(p.month)}</td>
                          <td>{isGapPoint(p) ? "—" : formatMoney(p.total)}</td>
                          <td>{isGapPoint(p) ? "—" : formatMoney(p.stocks_funds)}</td>
                          <td>{isGapPoint(p) ? "—" : formatMoney(p.cash)}</td>
                          <td>{isGapPoint(p) ? "—" : formatMoney(p.crypto)}</td>
                          <td>{isGapPoint(p) ? "—" : formatMoney(p.liabilities)}</td>
                          <td>{isGapPoint(p) ? "no data" : p.freshness_status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>

            <div className="whGrid2">
              <div className="whCard">
                <div className="whCardHead">
                  <div>
                    <div className="whCardTitle">Dividends</div>
                    <div className="whCardMeta">Derived from transactions — always exact.</div>
                  </div>
                  <div className="whCardMeta">
                    <strong className="whStatValue">{formatMoney(ttmDividends)}</strong> TTM
                  </div>
                </div>
                {dividendsState === "loading" ? (
                  <p className="muted" role="status">Loading…</p>
                ) : dividendBuckets.length === 0 ? (
                  <p className="muted">No dividend income in this range.</p>
                ) : (
                  <div className="whBarChart" role="img" aria-label="Monthly dividends">
                    {dividendBuckets.map((b) => (
                      <div className="whBarItem" key={b.bucket}>
                        <div className="whBarTrack">
                          <div
                            className="whBar whBarDividend"
                            style={{ height: `${Math.max(4, (b.net_received / dividendMax) * 100)}%` }}
                            title={`${monthLabel(b.bucket)}: ${formatMoney(b.net_received)}`}
                          />
                        </div>
                        <span className="whBarLabel">{monthLabel(b.bucket)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="whCard">
                <div className="whCardHead">
                  <div>
                    <div className="whCardTitle">Income vs spending</div>
                    <div className="whCardMeta">Last 6 months · cash-flow module</div>
                    {cashFlowState === "ready" ? <FxNote sources={[cashFlowFx]} /> : null}
                  </div>
                  <div className="whSeriesLegend">
                    <span className="whSeriesLegendItem">
                      <span className="whSeriesLegendKey" style={{ borderColor: "var(--wh-stocks)" }} /> income
                    </span>
                    <span className="whSeriesLegendItem">
                      <span className="whSeriesLegendKey" style={{ borderColor: "var(--wh-spend)" }} /> spending
                    </span>
                  </div>
                </div>
                {cashFlowState === "loading" ? (
                  <p className="muted" role="status">Loading…</p>
                ) : cashFlowTrend.length === 0 ? (
                  <p className="muted">No cash-flow data in this range.</p>
                ) : (
                  <div className="whBarChart whBarChartPaired" role="img" aria-label="Income vs spending">
                    {cashFlowTrend.map((p) => (
                      <div className="whBarItem" key={p.month}>
                        <div className="whBarTrack whBarTrackPaired">
                          <div
                            className="whBar"
                            style={{
                              height: `${Math.max(4, (p.inflows / cashFlowMax) * 100)}%`,
                              background: "var(--wh-stocks)",
                            }}
                            title={`${monthLabel(p.month)} income: ${formatMoney(p.inflows)}`}
                          />
                          <div
                            className="whBar"
                            style={{
                              height: `${Math.max(4, (p.outflows / cashFlowMax) * 100)}%`,
                              background: "var(--wh-spend)",
                            }}
                            title={`${monthLabel(p.month)} spending: ${formatMoney(p.outflows)}`}
                          />
                        </div>
                        <span className="whBarLabel">{monthLabel(p.month)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {selectedPoint && selectedFlags ? (
            <WealthDrilldownPanel
              month={selectedPoint.month}
              point={selectedPoint}
              prevPoint={selectedPrevPoint}
              flags={selectedFlags}
              baseCurrency={baseCurrency}
              formatMoney={formatMoney}
              onClose={() => setDrilldownOpen(false)}
            />
          ) : null}
          </div>
        )
      ) : null}
    </PageShell>
  );
}
