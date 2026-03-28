import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { StockHoldingsSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";
const PAGE_SIZE = 20;

export default function StockHoldings() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<StockHoldingsSummary | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [visibleCount, setVisibleCount] = useState<number>(PAGE_SIZE);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const data = await api.stockHoldingsSummary(month, baseCurrency);
        setSummary(data);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
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
  const holdings = useMemo(
    () => (summary?.top_holdings ?? []).filter((h) => h.asset_class !== "CASH" && h.asset_class !== "CRYPTO"),
    [summary],
  );
  const visibleHoldings = holdings.slice(0, visibleCount);
  const hasMore = visibleCount < holdings.length;
  const hasPrevious = visibleCount > PAGE_SIZE;

  return (
    <PageShell
      title="Stock Holdings"
      subtitle="Detailed equity and cash holdings snapshot."
      activeRoute="/holdings"
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
            <div className="stockHoldingsHeader">
              <h2>Top Holdings</h2>
              <div className="muted stockHoldingsMeta">
                Showing {visibleHoldings.length} of {holdings.length} positions
              </div>
            </div>
            <div className="stockHoldingsTableWrap">
              <table className="table stockHoldingsTable">
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
                  {visibleHoldings.map((h, idx) => (
                    <tr key={h.asset_id ?? `${h.symbol}-${idx}`}>
                      <td>{idx + 1}</td>
                      <td className="stockHoldingsSymbol">{h.symbol}</td>
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
                  {summary && holdings.length === 0 && (
                    <tr>
                      <td className="muted" colSpan={10}>No holdings available.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {holdings.length > 0 ? (
              <div className="stockHoldingsControls">
                <button
                  type="button"
                  className="btn"
                  onClick={() => setVisibleCount((current) => Math.max(PAGE_SIZE, current - PAGE_SIZE))}
                  disabled={!hasPrevious}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setVisibleCount((current) => Math.min(holdings.length, current + PAGE_SIZE))}
                  disabled={!hasMore}
                >
                  Next
                </button>
              </div>
            ) : null}
          </div>
        </section>
      )}
    </PageShell>
  );
}
