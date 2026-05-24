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

  const handleMonthChange = (nextMonth: string) => {
    setVisibleCount(PAGE_SIZE);
    setMonth(nextMonth);
  };

  const handleBaseCurrencyChange = (nextBaseCurrency: string) => {
    setVisibleCount(PAGE_SIZE);
    setBaseCurrency(nextBaseCurrency);
  };

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const stockData = await api.stockHoldingsSummary(month, baseCurrency);
        setSummary(stockData);
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
  const formatDelta = (value?: number | null, pct?: number | null) => {
    if (value == null) {
      return "—";
    }
    const sign = value >= 0 ? "+" : "-";
    const pctSuffix = pct == null ? "" : ` (${pct >= 0 ? "+" : "-"}${Math.abs(pct * 100).toFixed(1)}%)`;
    return `${sign}${formatMoney(Math.abs(value))}${pctSuffix}`;
  };
  const formatPnl = (holding: StockHoldingsSummary["top_holdings"][number]) => {
    if (
      holding.quantity == null
      || holding.avg_cost == null
      || holding.latest_price == null
      || !holding.quote_currency
    ) {
      return { amount: "—", pct: null, positive: true };
    }
    const pnl = holding.quantity * (holding.latest_price - holding.avg_cost);
    const pnlPct = holding.avg_cost > 0 ? ((holding.latest_price - holding.avg_cost) / holding.avg_cost) * 100 : null;
    return {
      amount: `${pnl >= 0 ? "+" : "-"}${formatNativeMoney(Math.abs(pnl), holding.quote_currency)}`,
      pct: pnlPct,
      positive: pnl >= 0,
    };
  };
  const holdings = useMemo(() => summary?.top_holdings ?? [], [summary]);
  const visibleHoldings = holdings.slice(0, visibleCount);
  const hasMore = visibleCount < holdings.length;
  const hasPrevious = visibleCount > PAGE_SIZE;

  return (
    <PageShell
      title="Stock Holdings"
      subtitle="Current equity holdings with quote freshness and snapshot geography comparisons."
      activeRoute="/holdings"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={handleMonthChange} />
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
              aria-label="Base currency"
              value={baseCurrency}
              onChange={(event) => handleBaseCurrencyChange(event.target.value)}
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
        <section className="grid g-mid stockHoldingsLayout">
          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Quote Freshness</h2>
              <div className="muted stockHoldingsMeta">
                Current holdings as of {summary?.current_holdings_as_of?.slice(0, 10) ?? "—"}
              </div>
            </div>
            <div className="split">
              <div className="mini">
                <h3>Fresh</h3>
                <div className="big small">{summary?.quote_freshness_summary?.fresh ?? 0}</div>
              </div>
              <div className="mini">
                <h3>Stale</h3>
                <div className="big small">{summary?.quote_freshness_summary?.stale ?? 0}</div>
              </div>
              <div className="mini">
                <h3>Missing</h3>
                <div className="big small">{summary?.quote_freshness_summary?.missing ?? 0}</div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Geography Breakdown</h2>
              <div className="muted stockHoldingsMeta">
                Current vs snapshot captured {summary?.net_worth_snapshot_as_of?.slice(0, 10) ?? "—"}
              </div>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Geography</th>
                  <th className="right">Current</th>
                  <th className="right">Snapshot</th>
                  <th className="right">Delta</th>
                </tr>
              </thead>
              <tbody>
                {(summary?.geography_breakdown ?? []).map((item) => (
                  <tr key={item.geography}>
                    <td>{item.geography}</td>
                    <td className="right">{formatMoney(item.current_value)}</td>
                    <td className="right">{formatMoney(item.snapshot_value)}</td>
                    <td className={`right ${item.delta_abs >= 0 ? "good" : "bad"}`}>{formatDelta(item.delta_abs, item.delta_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card stockHoldingsPrimaryCard">
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
                    <th>Asset</th>
                    <th className="right">Purchase Price</th>
                    <th className="right">Current Price</th>
                    <th className="right">Profit &amp; Loss</th>
                    <th>Quote freshness</th>
                    <th className="right">% NW</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleHoldings.map((h, idx) => {
                    const pnl = formatPnl(h);
                    return (
                      <tr key={h.asset_id ?? `${h.symbol}-${idx}`}>
                        <td>
                          <div className="stockHoldingsAssetCell">
                            <div className="stockHoldingsSymbol">{h.symbol}</div>
                            <div className="stockHoldingsAssetMeta">
                              <span>{h.platform ?? "—"}</span>
                              <span>{h.geo ?? "—"}</span>
                              <span>{formatQuantity(h.quantity)} shares</span>
                            </div>
                          </div>
                        </td>
                        <td className="right stockHoldingsPriceCell">{formatNativeMoney(h.avg_cost, h.quote_currency)}</td>
                        <td className="right stockHoldingsPriceCell">{formatNativeMoney(h.latest_price, h.quote_currency)}</td>
                        <td className={`right stockHoldingsPnlCell ${pnl.positive ? "good" : "bad"}`}>
                          <div>{pnl.amount}</div>
                          {pnl.pct == null ? null : <small>{pnl.pct >= 0 ? "+" : ""}{pnl.pct.toFixed(1)}%</small>}
                        </td>
                        <td>
                          <div>{h.quote_freshness_status ?? "missing"}</div>
                          <small className="muted">
                            {h.latest_trade_date?.slice(0, 10) ?? "—"}
                            {h.price_provider ? ` · ${h.price_provider}` : ""}
                          </small>
                        </td>
                        <td className="right stockHoldingsPercentCell">
                          <div>{h.percent_of_networth.toFixed(1)}%</div>
                          <small>{formatMoney(h.value)}</small>
                        </td>
                      </tr>
                    );
                  })}
                  {summary && holdings.length === 0 && (
                    <tr>
                      <td className="muted" colSpan={6}>No holdings available.</td>
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
