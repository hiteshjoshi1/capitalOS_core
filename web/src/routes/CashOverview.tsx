import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CashDeposits, CryptoSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import StackedBar from "../components/StackedBar";
import TrendBarChart from "../components/TrendBarChart";

type LoadState = "idle" | "loading" | "ready" | "error";

const STABLECOINS = new Set(["USDC", "USDT"]);
const STACKED_BAR_COLORS = ["#4f8cff", "#1fb981", "#f59f43", "#7d67ff", "#ef6ca8"];

type DonutItem = { label: string; value: number; percent: number };

function donutConicGradient(items: DonutItem[]): string {
  let offset = 0;
  const parts = items.map((item, idx) => {
    const next = offset + Math.max(0, item.percent);
    const part = `${STACKED_BAR_COLORS[idx % STACKED_BAR_COLORS.length]} ${offset.toFixed(2)}% ${next.toFixed(2)}%`;
    offset = next;
    return part;
  });
  if (offset < 100) {
    parts.push(`color-mix(in srgb, var(--line) 65%, transparent 35%) ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

export default function CashOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [cryptoSummary, setCryptoSummary] = useState<CryptoSummary | null>(null);
  const [cashDeposits, setCashDeposits] = useState<CashDeposits | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [crypto, deposits] = await Promise.all([
          api.cryptoSummary(month, baseCurrency),
          api.cashDeposits(month, baseCurrency),
        ]);
        setCryptoSummary(crypto);
        setCashDeposits(deposits);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = useCallback(
    (value?: number | null, maximumFractionDigits = 0) =>
      value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`,
    [currencyPrefix],
  );
  const formatCompactMoney = useCallback(
    (value?: number | null) =>
      value == null
        ? "—"
        : `${currencyPrefix} ${value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`,
    [currencyPrefix],
  );

  const stablecoins = useMemo(() => {
    const tokens = (cryptoSummary?.top_holdings ?? []).filter((t) => STABLECOINS.has((t.symbol || "").toUpperCase()));
    return tokens;
  }, [cryptoSummary]);

  const stablecoinTotal = stablecoins.reduce((acc, t) => acc + (t.value_base ?? 0), 0);

  const accountItems = useMemo(
    () => (cashDeposits?.items ?? []).map((item) => ({ label: item.source, value: item.value, percent: item.percent })),
    [cashDeposits],
  );

  const currencySegments = useMemo(() => {
    const breakdown = cashDeposits?.currency_breakdown ?? [];
    const sum = breakdown.reduce((acc, c) => acc + Math.max(0, c.current_value), 0) || 1;
    return breakdown.map((c, idx) => ({
      key: c.currency,
      label: c.currency,
      percent: (Math.max(0, c.current_value) / sum) * 100,
      color: STACKED_BAR_COLORS[idx % STACKED_BAR_COLORS.length],
      valueLabel: `${formatMoney(c.current_value)} (${c.delta_abs >= 0 ? "+" : "-"}${formatMoney(Math.abs(c.delta_abs))})`,
    }));
  }, [cashDeposits, formatMoney]);

  const trendPoints = useMemo(
    () =>
      (cashDeposits?.trend ?? [])
        .filter((point) => point.value != null)
        .map((point) => ({
          month: point.month,
          value: point.value as number,
          displayValue: formatCompactMoney(point.value),
          tone: "neutral" as const,
        })),
    [cashDeposits, formatCompactMoney],
  );

  const deltaPositive = (cashDeposits?.delta_abs ?? 0) >= 0;
  const deltaPct = cashDeposits?.delta_pct;

  return (
    <PageShell
      title="Cash Overview"
      subtitle="Bank cash, broker cash, and stablecoin balances."
      activeRoute="/cash"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="coPillBtn">
                        <span aria-hidden="true">{baseCurrency}</span>
            <select
              className="coPillBtnInput"
              aria-label="Base currency"
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
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
      {state === "loading" && <div className="card">Loading…</div>}
      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <div className="wealthOverviewLayout">
          <HeroMetricCard
            eyebrow="CURRENT CASH"
            value={formatMoney(cashDeposits?.current_total)}
            deltaChip={
              deltaPct == null
                ? null
                : { text: `${deltaPositive ? "+" : "-"}${Math.abs(deltaPct * 100).toFixed(1)}%`, positive: deltaPositive }
            }
            insightText={`Snapshot ${cashDeposits?.snapshot_cash_as_of?.slice(0, 10) ?? "—"} vs. current ${cashDeposits?.current_cash_as_of?.slice(0, 10) ?? "—"}`}
          />

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Allocation</p>
              <h2 className="cashFlowSectionTitle">Where the cash sits</h2>
            </div>
            {accountItems.length === 0 ? (
              <div className="card muted">No cash deposits yet.</div>
            ) : (
              <div className="card cashFlowDonutLayout" style={{ padding: 28 }} aria-label="Cash by account">
                <div className="cashFlowDonutChart" style={{ background: donutConicGradient(accountItems) }}>
                  <div className="cashFlowDonutCenter">
                    <span className="label">Total</span>
                    <strong>{formatMoney(cashDeposits?.total)}</strong>
                  </div>
                </div>
                <div className="cashFlowLegendList">
                  {accountItems.map((item, idx) => (
                    <div className="cashFlowLegendRow" key={item.label}>
                      <span className="cashFlowLegendLabel">
                        <i style={{ background: STACKED_BAR_COLORS[idx % STACKED_BAR_COLORS.length] }} />
                        <span className="cashFlowLegendText">{item.label}</span>
                      </span>
                      <span className="muted">
                        {formatMoney(item.value)} <strong>{item.percent.toFixed(1)}%</strong>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Signals</p>
              <h2 className="cashFlowSectionTitle">Currency mix and stablecoins</h2>
            </div>
            <div className="grid g-mid">
              <div className="card" style={{ padding: 24 }}>
                <p className="cashFlowCardTitle">Currency exposure</p>
                <StackedBar layout="rows" segments={currencySegments} ariaLabel="Currency mix" />
              </div>

              <div className="card" style={{ padding: 24 }}>
                <div className="cashFlowCardHeader" style={{ marginBottom: 6 }}>
                  <p className="cashFlowCardTitle" style={{ margin: 0 }}>Stablecoins</p>
                  <span className="muted">USDC / USDT</span>
                </div>
                <div className="big small">{formatMoney(stablecoinTotal)}</div>
                <div className="listRows" style={{ marginTop: 8 }}>
                  {stablecoins.length === 0 ? (
                    <p className="muted">No stablecoin balances found.</p>
                  ) : (
                    stablecoins.map((t) => (
                      <div className="listRow" key={`${t.symbol}-${t.chain}-${t.wallet_id ?? ""}`}>
                        <div className="listRowMain">
                          <span className="listRowTitle">{t.symbol}</span>
                          <span className="listRowMeta">
                            <span>{t.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })}</span>
                            <span>{t.chain.toUpperCase()}</span>
                          </span>
                        </div>
                        <div className="listRowValue">{formatMoney(t.value_base)}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </section>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Six-month cash trend</h2>
              <div className="muted stockHoldingsMeta">Snapshot-based month history</div>
            </div>
            <TrendBarChart points={trendPoints} ariaLabel="Six-month cash trend" />
          </div>
        </div>
      )}
    </PageShell>
  );
}
