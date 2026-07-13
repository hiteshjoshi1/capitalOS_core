import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { DashboardSummary, GeographyExposure } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import {
  buildTopNDistribution,
  computeLargestPositionRisk,
  computeTopNConcentrationRisk,
  formatLargestPosition,
  formatRiskPercent,
  riskStateClassName,
  RISK_LARGEST_POSITION_WARN_PCT,
  RISK_TOP5_TARGET_MAX_PCT,
  RISK_TOP5_TARGET_MIN_PCT,
  type TopN,
} from "../lib/risk";
import "../App.css";
import GeographyPieCard from "../components/dashboard/GeographyPieCard";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import SegmentedToggle from "../components/SegmentedToggle";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function WealthRisk() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [geographyExposure, setGeographyExposure] = useState<GeographyExposure | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [selectedTopN, setSelectedTopN] = useState<TopN>(5);
  const selectedBaseCurrency = baseCurrency || summary?.base_currency || "SGD";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setState("loading");
        const [summaryData, geographyData] = await Promise.all([
          api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
          api.dashboardGeographyExposure(month, baseCurrency),
        ]);
        if (cancelled) return;
        setSummary(summaryData);
        setGeographyExposure(geographyData);
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
  const cashPct = netWorthTotal ? ((summary?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;

  const holdings = summary?.top_holdings ?? [];
  const riskLargest = computeLargestPositionRisk(holdings, netWorthTotal);
  const riskTopN = computeTopNConcentrationRisk(holdings, netWorthTotal, selectedTopN);
  const topNDistribution = buildTopNDistribution(holdings, netWorthTotal, selectedTopN);
  const largestDisplayedPercent = Math.max(...topNDistribution.map((item) => item.percent), 0);

  return (
    <PageShell
      title="Wealth Risk"
      subtitle="Concentration signals and geographic exposure for the current snapshot."
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="coPillBtn">
                        <span aria-hidden="true">{selectedBaseCurrency}</span>
            <select
              className="coPillBtnInput"
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
          <section className="grid g-mid">
            <div className="card">
              <h2>Cash buffer</h2>
              <div className="big small">{cashPct.toFixed(1)}%</div>
              <div className="muted">{formatMoney(summary?.net_worth.cash)} of {formatMoney(netWorthTotal)} net worth</div>
            </div>

            <div className="card">
              <h2>Largest position</h2>
              <div className={`big small ${riskStateClassName(riskLargest.state)}`}>{formatLargestPosition(riskLargest)}</div>
              <div className="muted">
                Comfort threshold: <span className={riskStateClassName(riskLargest.state)}>{RISK_LARGEST_POSITION_WARN_PCT}%</span>
              </div>
            </div>

            <div className="card">
              <div className="stockHoldingsHeader">
                <h2>{`Top ${selectedTopN} concentration`}</h2>
                <SegmentedToggle
                  ariaLabel="Top N positions"
                  value={selectedTopN === 3 ? "3" : "5"}
                  onChange={(v) => setSelectedTopN(v === "3" ? 3 : 5)}
                  options={[
                    { value: "3", label: "Top 3" },
                    { value: "5", label: "Top 5" },
                  ]}
                />
              </div>
              <div className={`big small ${riskStateClassName(riskTopN.state)}`}>{formatRiskPercent(riskTopN.percent)}</div>
              <div className="muted">
                Target band: {RISK_TOP5_TARGET_MIN_PCT}–{RISK_TOP5_TARGET_MAX_PCT}%
              </div>
              {!riskTopN.hasFullSelection && riskTopN.hasData ? (
                <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                  {`Showing ${riskTopN.availableCount} of requested ${riskTopN.selectedN} positions.`}
                </div>
              ) : null}
            </div>
          </section>

          <section className="card riskPositionsCard">
            <div className="riskSectionHeader">
              <div>
                <div className="riskSectionEyebrow">Concentration</div>
                <h2>Where the top positions sit</h2>
              </div>
              <div className="muted stockHoldingsMeta">Share of total net worth</div>
            </div>
            {topNDistribution.length > 0 ? (
              <ul className="riskChartList">
                {topNDistribution.map((item) => (
                  <li className="riskChartRow" key={`${item.symbol}-${item.assetClass}`}>
                    <span className="riskChartIdentity">
                      <strong className="riskChartSymbol">{item.symbol}</strong>
                      <span className="riskChartMeta">{item.assetClass} · {formatMoney(item.value)}</span>
                    </span>
                    <div className="riskChartTrack">
                      <span
                        className="riskChartFill"
                        style={{ width: `${largestDisplayedPercent > 0 ? (item.percent / largestDisplayedPercent) * 100 : 0}%` }}
                        title={`${item.symbol}: ${formatRiskPercent(item.percent)}`}
                      ></span>
                    </div>
                    <strong className="riskChartPercent">{formatRiskPercent(item.percent)}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="riskNoData">No holdings concentration data for this month or net worth is not positive.</div>
            )}
          </section>

          <GeographyPieCard exposure={geographyExposure} formatMoney={formatMoney} />
        </div>
      ) : null}
    </PageShell>
  );
}
