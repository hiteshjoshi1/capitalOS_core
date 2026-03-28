import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { DashboardSummary, GeographyExposure } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import {
  buildTopNDistribution,
  computeLargestPositionRisk,
  computeTopNConcentrationRisk,
  type TopN,
} from "../lib/risk";
import "../App.css";
import ExposureLinkCard from "../components/dashboard/ExposureLinkCard";
import GeographyPieCard from "../components/dashboard/GeographyPieCard";
import RiskCard from "../components/dashboard/RiskCard";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function WealthOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [geographyExposure, setGeographyExposure] = useState<GeographyExposure | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [selectedTopN, setSelectedTopN] = useState<TopN>(5);

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
      } catch (e: unknown) {
        if (cancelled) return;
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [month, baseCurrency]);

  const selectedBaseCurrency = baseCurrency || summary?.base_currency || "SGD";
  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : selectedBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const netWorthTotal = summary?.net_worth.total ?? 0;
  const cashPct = netWorthTotal ? ((summary?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;
  const stocksPct = netWorthTotal ? ((summary?.net_worth.stocks_funds ?? 0) / netWorthTotal) * 100 : 0;
  const cryptoPct = netWorthTotal ? ((summary?.net_worth.crypto ?? 0) / netWorthTotal) * 100 : 0;

  const holdings = summary?.top_holdings ?? [];
  const riskLargest = computeLargestPositionRisk(holdings, netWorthTotal);
  const riskTopN = computeTopNConcentrationRisk(holdings, netWorthTotal, selectedTopN);
  const topNDistribution = buildTopNDistribution(holdings, netWorthTotal, selectedTopN);

  return (
    <PageShell
      title="Wealth Overview"
      subtitle="Asset split and concentration risk."
      activeRoute="/wealth"
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
        <>
          <section className="grid dashboardRow rowExposure">
            <ExposureLinkCard
              title="Stocks & Funds"
              value={formatMoney(summary.net_worth.stocks_funds)}
              subtitle={`${stocksPct.toFixed(1)}% of net worth`}
              to="/holdings"
            />
            <ExposureLinkCard
              title="Crypto"
              value={formatMoney(summary.net_worth.crypto)}
              subtitle={`${cryptoPct.toFixed(1)}% of net worth`}
              to="/crypto/holdings"
            />
            <ExposureLinkCard
              title="Cash"
              value={formatMoney(summary.net_worth.cash)}
              subtitle={`${cashPct.toFixed(1)}% of net worth`}
              to="/cash"
            />
          </section>

          <section className="grid dashboardRow rowCashAction">
            <RiskCard
              riskLargest={riskLargest}
              riskTopN={riskTopN}
              selectedTopN={selectedTopN}
              onSelectTopN={setSelectedTopN}
              hasRiskDistribution={topNDistribution.length > 0}
              topNDistribution={topNDistribution}
              formatMoney={formatMoney}
              cashPercent={cashPct}
            />
            <GeographyPieCard
              exposure={geographyExposure}
              formatMoney={formatMoney}
            />
          </section>
        </>
      ) : null}
    </PageShell>
  );
}
