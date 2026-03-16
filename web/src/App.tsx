import { useEffect, useState } from "react";
import { api } from "./lib/api";
import type {
  CreditCardSummary,
  CryptoSummary,
  DashboardSummary,
  PlatformAllocation,
  SpendingSummary,
  StockExposure,
} from "./lib/api";
import { useSelectedMonth } from "./lib/selectedMonth";
import {
  buildTopNDistribution,
  computeLargestPositionRisk,
  computeTopNConcentrationRisk,
} from "./lib/risk";
import type { TopN } from "./lib/risk";
import "./App.css";
import AllocationCard from "./components/dashboard/AllocationCard";
import DashboardLoading from "./components/dashboard/DashboardLoading";
import ExposureLinkCard from "./components/dashboard/ExposureLinkCard";
import NetWorthHeroCard from "./components/dashboard/NetWorthHeroCard";
import PlaceholderCard from "./components/dashboard/PlaceholderCard";
import RiskCard from "./components/dashboard/RiskCard";
import CreditCardCard from "./components/dashboard/CreditCardCard";
import MonthControl from "./components/MonthControl";
import PageShell from "./components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function App() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [health, setHealth] = useState<string>("(unknown)");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [platformAllocation, setPlatformAllocation] = useState<PlatformAllocation | null>(null);
  const [stockExposure, setStockExposure] = useState<StockExposure | null>(null);
  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [creditCardSummary, setCreditCardSummary] = useState<CreditCardSummary | null>(null);
  const [cryptoSummary, setCryptoSummary] = useState<CryptoSummary | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [selectedTopN, setSelectedTopN] = useState<TopN>(5);
  const [unmappedCount, setUnmappedCount] = useState<number | undefined>(undefined);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [h, s, pa, se, ss, cc, cs] = await Promise.all([
          api.health(),
          api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
          api.platformAllocation(month, baseCurrency),
          api.stockExposure(month, baseCurrency),
          api.spendingSummary(month, baseCurrency),
          api.creditCardSummary(month, baseCurrency),
          api.cryptoSummary(baseCurrency),
        ]);
        setHealth(h.status);
        setSummary(s);
        setPlatformAllocation(pa);
        setStockExposure(se);
        setSpendingSummary(ss);
        setCreditCardSummary(cc);
        setCryptoSummary(cs);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  useEffect(() => {
    (async () => {
      try {
        setUnmappedCount(undefined);
        const transactions = await api.unmappedTransactions(month);
        setUnmappedCount(transactions.length);
      } catch {
        setUnmappedCount(undefined);
      }
    })();
  }, [month]);

  const selectedBaseCurrency =
    baseCurrency ||
    summary?.base_currency ||
    spendingSummary?.base_currency ||
    creditCardSummary?.base_currency ||
    "SGD";
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
  const hasRiskDistribution = riskTopN.hasData && topNDistribution.length > 0;

  return (
    <PageShell
      title="CapitalOS Dashboard"
      activeRoute="/"
      unmappedCount={unmappedCount}
      userMenuSettings={(
        <>
          <div className="muted">API: {health}</div>
          <div className="muted">As of: {summary?.net_worth_as_of ?? "—"}</div>
          <label className="field">
            <span className="label">Base Currency</span>
            <select
              className="input"
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
      headerActions={<MonthControl month={month} onMonthChange={setMonth} />}
    >
      <div className="dashboardWrap">
        {state === "loading" ? <DashboardLoading /> : null}

        {state === "error" ? (
          <div className="card error">
            <div className="cardTitle">API error</div>
            <pre className="pre">{err}</pre>
            <div className="hint">
              Check: API running on <code>http://localhost:8000</code> and CORS env set.
            </div>
          </div>
        ) : null}

        {state === "ready" ? (
          <>
            <section className="grid dashboardRow row1">
              <NetWorthHeroCard
                summary={summary}
                formatMoney={formatMoney}
                cashPct={cashPct}
                stocksPct={stocksPct}
                cryptoPct={cryptoPct}
              />
            </section>

            <section className="grid dashboardRow row2">
              <ExposureLinkCard
                title="Cash Flow"
                value={formatMoney(spendingSummary?.net)}
                subtitle={
                  spendingSummary
                    ? `${spendingSummary.month} | Income ${formatMoney(spendingSummary.income_total)} | Expenses ${formatMoney(spendingSummary.expense_total)}`
                    : `No cash flow summary for ${month}`
                }
                to="/cash-flow"
              />
              <CreditCardCard
                month={month}
                summary={creditCardSummary}
                formatMoney={formatMoney}
              />
            </section>

            <section className="grid dashboardRow row3">
              <ExposureLinkCard
                title="Stock Exposure"
                value={formatMoney(stockExposure?.total)}
                subtitle={stockExposure?.as_of ?? "No stock snapshot"}
                to="/holdings"
              />
              <ExposureLinkCard
                title="Crypto Exposure"
                value={formatMoney(cryptoSummary?.total_crypto_base)}
                subtitle={cryptoSummary?.last_refreshed_at ?? "No crypto refresh yet"}
                to="/crypto/holdings"
              />
              <ExposureLinkCard
                title="Cash Exposure"
                value={formatMoney(summary?.net_worth.cash)}
                subtitle={`Balances: ${summary?.cash_balances?.length ?? 0} currencies`}
                to="/cash"
              />
            </section>

            <section className="grid dashboardRow row4">
              <RiskCard
                riskLargest={riskLargest}
                riskTopN={riskTopN}
                selectedTopN={selectedTopN}
                onSelectTopN={setSelectedTopN}
                hasRiskDistribution={hasRiskDistribution}
                topNDistribution={topNDistribution}
                formatMoney={formatMoney}
              />
              <AllocationCard
                title="Allocation by Geography"
                firstColumnLabel="Region"
                rows={(summary?.geography ?? []).map((item) => ({
                  key: item.country,
                  value: item.value,
                  percent: item.percent,
                }))}
                emptyLabel="No geography data yet."
                formatMoney={formatMoney}
              />
              <AllocationCard
                title="Allocation by Platform"
                firstColumnLabel="Platform"
                rows={(platformAllocation?.items ?? []).map((item) => ({
                  key: item.platform,
                  value: item.value,
                  percent: item.percent,
                }))}
                emptyLabel="No platform allocation data."
                formatMoney={formatMoney}
              />
            </section>

            <section className="grid dashboardRow row5">
              <PlaceholderCard
                title="Expense Breakdown"
                description="Category-level expense breakdown will appear after ingestion activation."
              />
              <PlaceholderCard
                title="Trends (Monthly)"
                description="Monthly trend charts are placeholders until ingestion history is available."
              />
            </section>
          </>
        ) : null}
      </div>
    </PageShell>
  );
}
