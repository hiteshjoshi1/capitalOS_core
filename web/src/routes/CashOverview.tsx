import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { DashboardSummary, CryptoSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

const STABLECOINS = new Set(["USDC", "USDT"]);

export default function CashOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [cryptoSummary, setCryptoSummary] = useState<CryptoSummary | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [dash, crypto] = await Promise.all([
          api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
          api.cryptoSummary(baseCurrency),
        ]);
        setSummary(dash);
        setCryptoSummary(crypto);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const stablecoins = useMemo(() => {
    const tokens = (cryptoSummary?.top_holdings ?? []).filter((t) => STABLECOINS.has((t.symbol || "").toUpperCase()));
    return tokens;
  }, [cryptoSummary]);

  const stablecoinTotal = stablecoins.reduce((acc, t) => acc + (t.value_base ?? 0), 0);

  return (
    <PageShell
      title="Cash Overview"
      subtitle="Bank cash, broker cash, and stablecoin balances."
      activeRoute="/cash"
      secondaryNavItem={{ label: "Ingest", to: "/ingest" }}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
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
        <section className="grid g-mid">
          <div className="card">
            <h2>Cash Balances</h2>
            <div className="mini">
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>By currency (base converted)</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Currency</th>
                    <th className="right">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.cash_balances?.map((c) => (
                    <tr key={c.currency}>
                      <td>{c.currency}</td>
                      <td className="right">{formatMoney(c.value)}</td>
                    </tr>
                  ))}
                  {summary?.cash_balances && summary.cash_balances.length === 0 && (
                    <tr>
                      <td className="muted" colSpan={2}>No cash balances yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h2>Stablecoins</h2>
            <div className="mini">
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>USDC / USDT holdings</div>
              <div className="big small">{formatMoney(stablecoinTotal)}</div>
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
      )}
    </PageShell>
  );
}
