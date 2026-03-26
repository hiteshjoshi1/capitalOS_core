import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./lib/api";
import type { DashboardBootstrap, SpendingSummary } from "./lib/api";
import { useSelectedMonth } from "./lib/selectedMonth";
import "./App.css";
import DashboardLoading from "./components/dashboard/DashboardLoading";
import ExposureLinkCard from "./components/dashboard/ExposureLinkCard";
import NetWorthHeroCard from "./components/dashboard/NetWorthHeroCard";
import MonthControl from "./components/MonthControl";
import PageShell from "./components/PageShell";

type BootstrapState = "idle" | "loading" | "ready" | "error";
type SpendingState = "idle" | "loading" | "ready";

export default function App() {
  const [bootstrapState, setBootstrapState] = useState<BootstrapState>("idle");
  const [bootstrapData, setBootstrapData] = useState<DashboardBootstrap | null>(null);
  const [err, setErr] = useState<string>("");

  const [spendingState, setSpendingState] = useState<SpendingState>("idle");
  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [unmappedCount, setUnmappedCount] = useState<number | undefined>(undefined);

  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  // Phase 1: bootstrap
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setBootstrapState("loading");
        setBootstrapData(null);
        setSpendingState("idle");
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

  // Phase 2: spending summary (triggered after bootstrap)
  useEffect(() => {
    if (bootstrapState !== "ready") return;
    let cancelled = false;
    (async () => {
      setSpendingState("loading");
      try {
        const ss = await api.spendingSummary(month, baseCurrency);
        if (cancelled) return;
        setSpendingSummary(ss);
        setSpendingState("ready");
      } catch {
        if (cancelled) return;
        setSpendingState("ready");
      }
    })();
    return () => { cancelled = true; };
  }, [bootstrapState, month, baseCurrency]);

  // Phase 2: unmapped count for action queue
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
    baseCurrency || bootstrapData?.base_currency || "SGD";
  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : selectedBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const netWorthTotal = bootstrapData?.net_worth.total ?? 0;
  const cashPct = netWorthTotal ? ((bootstrapData?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;
  const stocksPct = netWorthTotal ? ((bootstrapData?.net_worth.stocks_funds ?? 0) / netWorthTotal) * 100 : 0;
  const cryptoPct = netWorthTotal ? ((bootstrapData?.net_worth.crypto ?? 0) / netWorthTotal) * 100 : 0;
  const liabilitiesPct = netWorthTotal
    ? (Math.abs(bootstrapData?.net_worth.liabilities ?? 0) / netWorthTotal) * 100
    : 0;

  // Minimal DashboardSummary-compatible object for NetWorthHeroCard
  const heroSummary = bootstrapData
    ? {
        net_worth: bootstrapData.net_worth,
        net_worth_as_of: bootstrapData.net_worth_as_of,
        net_worth_change: null,
        cash_balances: undefined,
        cash_percent: bootstrapData.cash_percent ?? cashPct,
        as_of_month: bootstrapData.as_of_month,
        base_currency: bootstrapData.base_currency,
        snapshot_day: bootstrapData.snapshot_day,
        geography: [] as Array<{ country: string; value: number; percent: number }>,
        cash_flow: { income: 0, expenses: 0, net: 0, savings_rate: null as null },
        top_holdings: [] as Array<{
          asset_id: number | null;
          symbol: string;
          asset_class: string;
          value: number;
          percent_of_networth: number;
        }>,
      }
    : null;

  return (
    <PageShell
      title="Dashboard"
      headerActions={(
        <>
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
          <MonthControl month={month} onMonthChange={setMonth} />
        </>
      )}
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
            {/* Row 1: Net Worth Hero */}
            <section className="grid dashboardRow row1">
              <NetWorthHeroCard
                summary={heroSummary}
                formatMoney={formatMoney}
                cashPct={cashPct}
                stocksPct={stocksPct}
                cryptoPct={cryptoPct}
              />
            </section>

            {/* Row 2: Exposure Link Cards */}
            <section className="grid dashboardRow rowExposure">
              <ExposureLinkCard
                title="Stocks &amp; Funds"
                value={formatMoney(bootstrapData?.stock_exposure_total)}
                subtitle={`${stocksPct.toFixed(1)}% of net worth`}
                to="/holdings"
              />
              <ExposureLinkCard
                title="Crypto"
                value={formatMoney(bootstrapData?.crypto_exposure_total)}
                subtitle={`${cryptoPct.toFixed(1)}% of net worth`}
                to="/crypto/holdings"
              />
              <ExposureLinkCard
                title="Cash"
                value={formatMoney(bootstrapData?.net_worth.cash)}
                subtitle={`${cashPct.toFixed(1)}% of net worth`}
                to="/cash"
              />
              <ExposureLinkCard
                title="Liabilities"
                value={formatMoney(Math.abs(bootstrapData?.net_worth.liabilities ?? 0))}
                subtitle={`${liabilitiesPct.toFixed(1)}% of net worth`}
                to="/credit-cards"
              />
            </section>

            {/* Row 3: Cash Flow summary + Action Queue */}
            <section className="grid dashboardRow rowCashAction">
              {spendingState !== "ready" ? (
                <div className="card loadingCard" aria-label="Loading cash flow">
                  <div className="skeleton title"></div>
                  <div className="skeleton block"></div>
                </div>
              ) : (
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
              )}

              <div className="card actionQueue" aria-label="Action queue">
                <h2>Action Queue</h2>
                <div className="actionQueueItems">
                  {unmappedCount != null && unmappedCount > 0 ? (
                    <Link to="/cash-flow/mapping" className="actionQueueItem">
                      <span className="actionQueueBadge">{unmappedCount}</span>
                      <span>Unmapped transactions need categorization</span>
                    </Link>
                  ) : (
                    <div className="muted actionQueueEmpty">No pending actions</div>
                  )}
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </PageShell>
  );
}

