import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CashFlowTrendPoint, DividendSummaryBucket, WealthTimeline } from "../lib/api";
import PageShell from "../components/PageShell";
import WealthHistoryChart, { type WealthHistoryChartMode } from "../components/WealthHistoryChart";
import WealthAttributionStrip from "../components/WealthAttributionStrip";
import WealthDrilldownPanel from "../components/WealthDrilldownPanel";
import { computeMonthFlags, isGapPoint } from "../lib/wealthHistoryAnalysis";
import "../App.css";

type LoadState = "idle" | "loading" | "ready" | "error";

const RANGE_OPTIONS: { label: string; months: number }[] = [
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "2Y", months: 24 },
  { label: "All", months: 60 },
];

function shiftMonth(month: string, delta: number): string {
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;
  const dt = new Date(Date.UTC(year, monthIndex + delta, 1));
  const nextYear = dt.getUTCFullYear();
  const nextMonth = String(dt.getUTCMonth() + 1).padStart(2, "0");
  return `${nextYear}-${nextMonth}`;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  const year = Number(y);
  const mon = Number(m);
  if (!Number.isFinite(year) || !Number.isFinite(mon)) return month;
  return new Date(year, mon - 1, 1).toLocaleString("en", { month: "short", year: "2-digit" });
}

export default function WealthHistory() {
  const [range, setRange] = useState<number>(24);
  const [mode, setMode] = useState<WealthHistoryChartMode>("total");
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  const [timelineState, setTimelineState] = useState<LoadState>("idle");
  const [timelineErr, setTimelineErr] = useState("");
  const [timeline, setTimeline] = useState<WealthTimeline | null>(null);
  const [backfilling, setBackfilling] = useState(false);

  const [dividendsState, setDividendsState] = useState<LoadState>("idle");
  const [dividendBuckets, setDividendBuckets] = useState<DividendSummaryBucket[]>([]);

  const [cashFlowState, setCashFlowState] = useState<LoadState>("idle");
  const [cashFlowTrend, setCashFlowTrend] = useState<CashFlowTrendPoint[]>([]);

  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);

  const fetchTimeline = useCallback(async () => {
    setTimelineState("loading");
    try {
      const data = await api.netWorthTimeline(range, baseCurrency);
      setTimeline(data);
      setTimelineState("ready");
    } catch (error: unknown) {
      setTimelineErr(error instanceof Error ? error.message : String(error));
      setTimelineState("error");
    }
  }, [range, baseCurrency]);

  const fetchDividends = useCallback(async () => {
    setDividendsState("loading");
    try {
      const fromMonth = shiftMonth(currentMonth(), -(range - 1));
      const data = await api.dividendsSummary(fromMonth, currentMonth(), "month", baseCurrency);
      setDividendBuckets(data.buckets);
      setDividendsState("ready");
    } catch {
      setDividendsState("error");
    }
  }, [range, baseCurrency]);

  const fetchCashFlow = useCallback(async () => {
    setCashFlowState("loading");
    try {
      const data = await api.cashFlowDetail(currentMonth(), baseCurrency);
      setCashFlowTrend(data.analytics.trend);
      setCashFlowState("ready");
    } catch {
      setCashFlowState("error");
    }
  }, [baseCurrency]);

  useEffect(() => {
    void fetchTimeline();
  }, [fetchTimeline]);

  useEffect(() => {
    void fetchDividends();
    void fetchCashFlow();
  }, [fetchDividends, fetchCashFlow]);

  const handleGenerateHistory = useCallback(async () => {
    setBackfilling(true);
    try {
      await api.netWorthTimelineBackfill(range, baseCurrency);
      await fetchTimeline();
    } finally {
      setBackfilling(false);
    }
  }, [range, baseCurrency, fetchTimeline]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : baseCurrency;
  const formatMoney = useCallback(
    (value?: number | null, maximumFractionDigits = 0) =>
      value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`,
    [currencyPrefix],
  );
  const formatMoneyShort = useCallback(
    (value?: number | null) => {
      if (value == null) return "—";
      const abs = Math.abs(value);
      const sign = value < 0 ? "-" : "";
      if (abs >= 1_000_000) return `${sign}${currencyPrefix} ${(abs / 1_000_000).toFixed(1)}M`;
      if (abs >= 1_000) return `${sign}${currencyPrefix} ${(abs / 1_000).toFixed(0)}K`;
      return `${sign}${currencyPrefix} ${abs.toFixed(0)}`;
    },
    [currencyPrefix],
  );

  const hasAnyData = useMemo(() => (timeline ? timeline.points.some((p) => !isGapPoint(p)) : false), [timeline]);

  const monthFlags = useMemo(() => computeMonthFlags(timeline?.points ?? []), [timeline]);
  const selectedPoint = useMemo(
    () => (selectedMonth ? (timeline?.points.find((p) => p.month === selectedMonth) ?? null) : null),
    [timeline, selectedMonth],
  );
  const selectedFlags = selectedMonth ? monthFlags.get(selectedMonth) : null;
  const selectedPrevPoint = useMemo(() => {
    if (!selectedFlags?.comparedToMonth) return null;
    return timeline?.points.find((p) => p.month === selectedFlags.comparedToMonth) ?? null;
  }, [timeline, selectedFlags]);

  // Range/currency changes invalidate any drill-down selection from the previous data.
  useEffect(() => {
    setSelectedMonth(null);
  }, [range, baseCurrency]);

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
        <label className="coPillBtn">
          <span aria-hidden="true">{baseCurrency}</span>
          <select
            className="coPillBtnInput"
            aria-label="Base currency"
            value={baseCurrency}
            onChange={(event) => setBaseCurrency(event.target.value)}
          >
            <option value="SGD">SGD</option>
            <option value="USD">USD</option>
            <option value="HKD">HKD</option>
            <option value="INR">INR</option>
          </select>
        </label>
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

      {timelineState === "loading" || timelineState === "idle" ? <div className="card">Loading…</div> : null}
      {timelineState === "error" ? (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{timelineErr}</pre>
        </div>
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
                onSelectMonth={setSelectedMonth}
              />

              <div className="whAttribDivider" />
              <WealthAttributionStrip
                points={timeline.points}
                formatMoney={formatMoney}
                selectedMonth={selectedMonth}
                onSelectMonth={setSelectedMonth}
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
                  <p className="muted">Loading…</p>
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
                  <p className="muted">Loading…</p>
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
              onClose={() => setSelectedMonth(null)}
            />
          ) : null}
          </div>
        )
      ) : null}
    </PageShell>
  );
}
