import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CashDeposits, CryptoSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import ExposurePieCard from "../components/ExposurePieCard";
import StackedBar from "../components/StackedBar";
import TrendBarChart from "../components/TrendBarChart";

type LoadState = "idle" | "loading" | "ready" | "error";

const STABLECOINS = new Set(["USDC", "USDT"]);
const STACKED_BAR_COLORS = ["#4f8cff", "#1fb981", "#f59f43", "#7d67ff", "#ef6ca8"];

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
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatCompactMoney = (value?: number | null) =>
    value == null
      ? "—"
      : `${currencyPrefix} ${value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`;

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
  }, [cashDeposits, currencyPrefix]);

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
    [cashDeposits, currencyPrefix],
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

          <ExposurePieCard
            title="Where the cash sits"
            subtitle={`${accountItems.length} accounts`}
            items={accountItems}
            totalLabel={formatMoney(cashDeposits?.total)}
            formatMoney={formatMoney}
            ariaLabel="Cash by account"
          />

          <section className="grid g-mid">
            <div className="card">
              <h2>Currency mix</h2>
              <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>Current value and delta vs. prior snapshot</div>
              <StackedBar segments={currencySegments} ariaLabel="Currency mix" />
            </div>

            <div className="card">
              <h2>Stablecoins</h2>
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>USDC / USDT holdings</div>
              <div className="big small">{formatMoney(stablecoinTotal)}</div>
              <div className="tableWrap">
                <table className="table" style={{ marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>Token</th>
                      <th className="right">Qty</th>
                      <th className="right">Value</th>
                      <th>Chain</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stablecoins.map((t) => (
                      <tr key={`${t.symbol}-${t.chain}-${t.wallet_id ?? ""}`}>
                        <td>{t.symbol}</td>
                        <td className="right">{t.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })}</td>
                        <td className="right">{formatMoney(t.value_base)}</td>
                        <td className="muted">{t.chain.toUpperCase()}</td>
                      </tr>
                    ))}
                    {stablecoins.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={4}>No stablecoin balances found.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
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
