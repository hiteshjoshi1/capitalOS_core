import { useEffect, useRef, useState } from "react";
import { api } from "./lib/api";
import type {
  CreditCardSummary,
  CryptoSummary,
  DashboardBootstrap,
  DashboardSummary,
  PlatformAllocation,
  SpendingSummary,
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

type BootstrapState = "idle" | "loading" | "ready" | "error";
type SecondaryState = "idle" | "loading" | "ready";

export default function App() {
  // Phase 1: bootstrap (hero + exposure)
  const [bootstrapState, setBootstrapState] = useState<BootstrapState>("idle");
  const [bootstrapData, setBootstrapData] = useState<DashboardBootstrap | null>(null);
  const [err, setErr] = useState<string>("");
  const [health, setHealth] = useState<string>("(unknown)");
  const healthFetchedRef = useRef(false);

  // Phase 2: secondary panels
  const [secondaryState, setSecondaryState] = useState<SecondaryState>("idle");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [platformAllocation, setPlatformAllocation] = useState<PlatformAllocation | null>(null);
  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [creditCardSummary, setCreditCardSummary] = useState<CreditCardSummary | null>(null);
  const [cryptoSummary, setCryptoSummary] = useState<CryptoSummary | null>(null);

  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [selectedTopN, setSelectedTopN] = useState<TopN>(5);
  const [unmappedCount, setUnmappedCount] = useState<number | undefined>(undefined);

  // Phase 1: bootstrap fetch
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setBootstrapState("loading");
        setBootstrapData(null);
        setSummary(null);
        setSecondaryState("idle");
        const bootstrap = await api.dashboardBootstrap(month, baseCurrency);
        if (cancelled) return;
        setBootstrapData(bootstrap);
        setBootstrapState("ready");
      } catch (e: unknown) {
        if (cancelled) return;
        setErr(e instanceof Error ? e.message : String(e));
        setBootstrapState("error");
      }
    })();
    return () => { cancelled = true; };
  }, [month, baseCurrency]);

  // Phase 2: secondary panels — triggered after bootstrap completes
  // Tier A: above-fold data loaded immediately after bootstrap
  // Tier B: below-fold data deferred via idle callback after Tier A resolves
  useEffect(() => {
    if (bootstrapState !== "ready") return;
    let cancelled = false;
    (async () => {
      setSecondaryState("loading");
      try {
        // Tier A: visible above-fold secondary cards
        const [s, pa] = await Promise.all([
          api.dashboardSummary(month, undefined, baseCurrency, true),
          api.platformAllocation(month, baseCurrency),
        ]);
        if (cancelled) return;
        setSummary(s);
        setPlatformAllocation(pa);

        // Tier B: below-fold panels, deferred until after Tier A settles
        await new Promise<void>((resolve) => {
          if (typeof requestIdleCallback !== "undefined") {
            requestIdleCallback(() => resolve());
          } else {
            setTimeout(resolve, 0);
          }
        });
        if (cancelled) return;

        const [ss, cc, cs] = await Promise.all([
          api.spendingSummary(month, baseCurrency),
          api.creditCardSummary(month, baseCurrency),
          api.cryptoSummary(baseCurrency),
        ]);
        if (cancelled) return;
        setSpendingSummary(ss);
        setCreditCardSummary(cc);
        setCryptoSummary(cs);
        setSecondaryState("ready");
      } catch {
        if (cancelled) return;
        setSecondaryState("ready");
      }
    })();
    return () => { cancelled = true; };
  }, [bootstrapState, month, baseCurrency]);

  useEffect(() => {
    if (bootstrapState !== "ready") return;
    (async () => {
      try {
        setUnmappedCount(undefined);
        const transactions = await api.unmappedTransactions(month);
        setUnmappedCount(transactions.length);
      } catch {
        setUnmappedCount(undefined);
      }
    })();
  }, [bootstrapState, month]);

  const selectedBaseCurrency =
    baseCurrency ||
    bootstrapData?.base_currency ||
    summary?.base_currency ||
    spendingSummary?.base_currency ||
    creditCardSummary?.base_currency ||
    "SGD";
  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : selectedBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  // Derive totals — prefer bootstrap data for first paint, secondary for richer views
  const netWorthTotal = bootstrapData?.net_worth.total ?? 0;
  const cashPct = netWorthTotal ? ((bootstrapData?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;
  const stocksPct = netWorthTotal ? ((bootstrapData?.net_worth.stocks_funds ?? 0) / netWorthTotal) * 100 : 0;
  const cryptoPct = netWorthTotal ? ((bootstrapData?.net_worth.crypto ?? 0) / netWorthTotal) * 100 : 0;

  // Secondary-only data
  const holdings = summary?.top_holdings ?? [];
  const riskLargest = computeLargestPositionRisk(holdings, netWorthTotal);
  const riskTopN = computeTopNConcentrationRisk(holdings, netWorthTotal, selectedTopN);
  const topNDistribution = buildTopNDistribution(holdings, netWorthTotal, selectedTopN);
  const hasRiskDistribution = riskTopN.hasData && topNDistribution.length > 0;
  const cashPercent = bootstrapData?.cash_percent ?? cashPct;

  // Build a minimal DashboardSummary-compatible object from bootstrap for NetWorthHeroCard
  const heroSummary = bootstrapData
    ? {
        net_worth: bootstrapData.net_worth,
        net_worth_as_of: bootstrapData.net_worth_as_of,
        net_worth_change: summary?.net_worth_change ?? null,
        cash_balances: summary?.cash_balances,
        cash_percent: bootstrapData.cash_percent ?? cashPct,
        as_of_month: bootstrapData.as_of_month,
        base_currency: bootstrapData.base_currency,
        snapshot_day: bootstrapData.snapshot_day,
        geography: summary?.geography ?? [],
        cash_flow: summary?.cash_flow ?? { income: 0, expenses: 0, net: 0, savings_rate: null },
        top_holdings: summary?.top_holdings ?? [],
      }
    : summary;

  const handleUserMenuOpen = () => {
    if (healthFetchedRef.current) return;
    healthFetchedRef.current = true;
    api.health().then((h) => setHealth(h.status)).catch(() => {});
  };

  return (
    <PageShell
      title="CapitalOS Dashboard"
      activeRoute="/"
      unmappedCount={unmappedCount}
      onUserMenuOpen={handleUserMenuOpen}
      userMenuSettings={(
        <>
          <div className="muted">API: {health}</div>
          <div className="muted">As of: {bootstrapData?.net_worth_as_of ?? "—"}</div>
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
        {bootstrapState === "loading" ? <DashboardLoading /> : null}

        {bootstrapState === "error" ? (
          <div className="card error">
            <div className="cardTitle">API error</div>
            <pre className="pre">{err}</pre>
            <div className="hint">
              Check: API running on <code>http://localhost:8000</code> and CORS env set.
            </div>
          </div>
        ) : null}

        {bootstrapState === "ready" ? (
          <>
            <section className="grid dashboardRow row1">
              <NetWorthHeroCard
                summary={heroSummary}
                formatMoney={formatMoney}
                cashPct={cashPct}
                stocksPct={stocksPct}
                cryptoPct={cryptoPct}
              />
            </section>

            <section className="grid dashboardRow row2">
              <ExposureLinkCard
                title="Stock Exposure"
                value={formatMoney(bootstrapData?.stock_exposure_total)}
                subtitle={bootstrapData?.net_worth_as_of ?? "No stock snapshot"}
                to="/holdings"
              />
              <ExposureLinkCard
                title="Crypto Exposure"
                value={formatMoney(bootstrapData?.crypto_exposure_total)}
                subtitle={cryptoSummary?.last_refreshed_at ?? bootstrapData?.net_worth_as_of ?? "No crypto data"}
                to="/crypto/holdings"
              />
              <ExposureLinkCard
                title="Cash Exposure"
                value={formatMoney(bootstrapData?.net_worth.cash)}
                subtitle={`Balances: ${summary?.cash_balances?.length ?? 0} currencies`}
                to="/cash"
              />
            </section>

            <section className="grid dashboardRow row3">
              {secondaryState !== "ready" ? (
                <>
                  <div className="card loadingCard" aria-label="Loading cash flow">
                    <div className="skeleton title"></div>
                    <div className="skeleton block"></div>
                  </div>
                  <div className="card loadingCard" aria-label="Loading credit cards">
                    <div className="skeleton title"></div>
                    <div className="skeleton block"></div>
                  </div>
                </>
              ) : (
                <>
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
                </>
              )}
            </section>

            <section className="grid dashboardRow row4">
              {secondaryState !== "ready" ? (
                <>
                  <div className="card loadingCard" aria-label="Loading risk">
                    <div className="skeleton title"></div>
                    <div className="skeleton block"></div>
                  </div>
                  <div className="card loadingCard" aria-label="Loading geography">
                    <div className="skeleton title"></div>
                    <div className="skeleton block"></div>
                  </div>
                  <div className="card loadingCard" aria-label="Loading platform allocation">
                    <div className="skeleton title"></div>
                    <div className="skeleton block"></div>
                  </div>
                </>
              ) : (
                <>
                  <RiskCard
                    riskLargest={riskLargest}
                    riskTopN={riskTopN}
                    selectedTopN={selectedTopN}
                    onSelectTopN={setSelectedTopN}
                    hasRiskDistribution={hasRiskDistribution}
                    topNDistribution={topNDistribution}
                    formatMoney={formatMoney}
                    cashPercent={cashPercent}
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
                </>
              )}
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
