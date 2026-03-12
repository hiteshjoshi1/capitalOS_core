import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { DashboardSummary } from "../lib/api";
import "../App.css";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

export default function StockHoldings() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [month] = useState<string>(currentMonthYYYYMM());
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const data = await api.dashboardSummary(month, "prev_month,prev_year", baseCurrency);
        setSummary(data);
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
  const formatQuantity = (value?: number | null) =>
    value == null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  const formatNativeMoney = (value?: number | null, quoteCurrency?: string, maximumFractionDigits = 2) => {
    if (value == null || !quoteCurrency) {
      return "—";
    }
    return `${quoteCurrency.toUpperCase()} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  };

  return (
    <PageShell
      title="Stock Holdings"
      subtitle="Detailed equity and cash holdings snapshot."
      activeRoute="/holdings"
      secondaryNavItem={{ label: "Ingest", to: "/ingest" }}
      headerActions={(
        <label className="pill">
          <span>Base</span>
          <select
            className="monthInput"
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
            <h2>Top Holdings</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Asset</th>
                  <th>Class</th>
                  <th className="right">% NW</th>
                  <th className="right">Value</th>
                  <th className="right">Shares</th>
                  <th className="right">Purchase Price</th>
                  <th className="right">Current Price</th>
                  <th>Geo</th>
                  <th>Platform</th>
                </tr>
              </thead>
              <tbody>
                {summary?.top_holdings
                  ?.filter((h) => h.asset_class !== "CASH")
                  .map((h, idx) => (
                  <tr key={h.asset_id}>
                    <td>{idx + 1}</td>
                    <td>{h.symbol}</td>
                    <td className="muted">{h.asset_class}</td>
                    <td className="right">{h.percent_of_networth.toFixed(1)}%</td>
                    <td className="right">{formatMoney(h.value)}</td>
                    <td className="right">{formatQuantity(h.quantity)}</td>
                    <td className="right">{formatNativeMoney(h.avg_cost, h.quote_currency)}</td>
                    <td className="right">{formatNativeMoney(h.latest_price, h.quote_currency)}</td>
                    <td className="muted">{h.geo ?? "—"}</td>
                    <td className="muted">{h.platform ?? "—"}</td>
                  </tr>
                ))}
                {summary && summary.top_holdings.filter((h) => h.asset_class !== "CASH").length === 0 && (
                  <tr>
                    <td className="muted" colSpan={10}>No holdings available.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </PageShell>
  );
}
