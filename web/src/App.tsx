import { useEffect, useState } from "react";
import { api } from "./lib/api";
import type { DashboardBootstrap, DashboardSummary, SpendingSummary } from "./lib/api";
import { useSelectedMonth } from "./lib/selectedMonth";
import "./App.css";
import DashboardLoading from "./components/dashboard/DashboardLoading";
import NetWorthHeroCard from "./components/dashboard/NetWorthHeroCard";
import MonthControl from "./components/MonthControl";
import PageShell from "./components/PageShell";

type BootstrapState = "idle" | "loading" | "ready" | "error";

export default function App() {
  const [bootstrapState, setBootstrapState] = useState<BootstrapState>("idle");
  const [bootstrapData, setBootstrapData] = useState<DashboardBootstrap | null>(null);
  const [err, setErr] = useState<string>("");

  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [netWorthChange, setNetWorthChange] = useState<DashboardSummary["net_worth_change"]>(null);

  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  // Phase 1: bootstrap
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setBootstrapState("loading");
        setBootstrapData(null);
        setSpendingSummary(null);
        setNetWorthChange(null);
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
      try {
        const ss = await api.spendingSummary(month, baseCurrency);
        if (cancelled) return;
        setSpendingSummary(ss);
      } catch {
        if (cancelled) return;
      }
    })();
    return () => { cancelled = true; };
  }, [bootstrapState, month, baseCurrency]);

  // Phase 3: net-worth deltas (lightweight follow-up after bootstrap)
  useEffect(() => {
    if (bootstrapState !== "ready") return;
    let cancelled = false;
    (async () => {
      try {
        const delta = await api.dashboardNetWorthChange(month, baseCurrency);
        if (cancelled) return;
        setNetWorthChange(delta.net_worth_change ?? null);
      } catch {
        if (cancelled) return;
      }
    })();
    return () => { cancelled = true; };
  }, [bootstrapState, month, baseCurrency]);

  const selectedBaseCurrency =
    baseCurrency || bootstrapData?.base_currency || "SGD";
  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : selectedBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const netWorthTotal = bootstrapData?.net_worth.total ?? 0;
  const cashPct = netWorthTotal ? ((bootstrapData?.net_worth.cash ?? 0) / netWorthTotal) * 100 : 0;
  const stocksPct = netWorthTotal ? ((bootstrapData?.net_worth.stocks_funds ?? 0) / netWorthTotal) * 100 : 0;
  const cryptoPct = netWorthTotal ? ((bootstrapData?.net_worth.crypto ?? 0) / netWorthTotal) * 100 : 0;
  // Minimal DashboardSummary-compatible object for NetWorthHeroCard
  const heroSummary = bootstrapData
    ? {
        net_worth: bootstrapData.net_worth,
        net_worth_as_of: bootstrapData.net_worth_as_of,
        net_worth_change: netWorthChange,
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
      title="CapitalOS Dashboard"
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
                cashFlowNet={spendingSummary?.net}
                cashFlowMonth={spendingSummary?.month}
              />
            </section>

            {/* Row 2: Action Queue */}
            <section className="grid dashboardRow rowActionOnly">
              <div className="card actionQueue" aria-label="Action queue">
                <h2>Action Queue</h2>
                <div className="actionQueueItems">
                  <div className="muted actionQueueEmpty">No pending actions</div>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </PageShell>
  );
}
