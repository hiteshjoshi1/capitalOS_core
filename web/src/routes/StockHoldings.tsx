import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { StockHoldingsSummary } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import ExposurePieCard from "../components/ExposurePieCard";
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
  const [refreshing, setRefreshing] = useState<boolean>(false);

  const handleMonthChange = (nextMonth: string) => {
    setVisibleCount(PAGE_SIZE);
    setMonth(nextMonth);
  };

  const handleBaseCurrencyChange = (nextBaseCurrency: string) => {
    setVisibleCount(PAGE_SIZE);
    setBaseCurrency(nextBaseCurrency);
  };

  const loadSummary = async () => {
    setErr("");
    setState("loading");
    const stockData = await api.stockHoldingsSummary(month, baseCurrency);
    setSummary(stockData);
    setState("ready");
  };

  useEffect(() => {
    (async () => {
      try {
        await loadSummary();
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const onRefresh = async () => {
    try {
      setRefreshing(true);
      await api.marketDataRefreshNow();
      await loadSummary();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setState("error");
    } finally {
      setRefreshing(false);
    }
  };

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatQuantity = (value?: number | null) =>
    value == null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  const formatNativeMoney = (value?: number | null, quoteCurrency?: string, maximumFractionDigits = 2) => {
    if (value == null || !quoteCurrency) {
      return "—";
    }
    return `${quoteCurrency.toUpperCase()} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
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
  const stockCurrentTotal = summary?.stock_current_total ?? 0;
  const geographyPieItems = useMemo(
    () => (summary?.geography_breakdown ?? [])
      .filter((item) => item.current_value > 0)
      .map((item) => ({
        label: item.geography,
        value: item.current_value,
        percent: stockCurrentTotal > 0 ? (item.current_value / stockCurrentTotal) * 100 : 0,
      })),
    [stockCurrentTotal, summary?.geography_breakdown],
  );
  const platformPieItems = useMemo(
    () => (summary?.platform_breakdown ?? [])
      .filter((item) => item.current_value > 0)
      .map((item) => ({
        label: formatPlatformLabel(item.key),
        value: item.current_value,
        percent: item.percent,
      })),
    [summary?.platform_breakdown],
  );

  return (
    <PageShell
      title="Stock Holdings"
      subtitle="Current equity holdings with quote freshness and snapshot geography comparisons."
      activeRoute="/holdings"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      headerActions={(
        <>
          <button className="btn" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Refreshing..." : "Refresh now"}
          </button>
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
          <div className="card stockFreshnessCard">
            <div className="stockHoldingsHeader">
              <h2>Quote Freshness</h2>
              <div className="muted stockHoldingsMeta">
                Current holdings as of {summary?.current_holdings_as_of?.slice(0, 10) ?? "—"}
              </div>
            </div>
            <div className="stockFreshnessPills">
              <div className="stockFreshnessPill stockFreshnessPillFresh">
                <span>Fresh</span>
                <strong>{summary?.quote_freshness_summary?.fresh ?? 0}</strong>
              </div>
              <div className="stockFreshnessPill stockFreshnessPillStale">
                <span>Stale</span>
                <strong>{summary?.quote_freshness_summary?.stale ?? 0}</strong>
              </div>
              <div className="stockFreshnessPill stockFreshnessPillMissing">
                <span>Missing</span>
                <strong>{summary?.quote_freshness_summary?.missing ?? 0}</strong>
              </div>
            </div>
          </div>

          <ExposurePieCard
            title="Geography Breakdown"
            subtitle={`Stock exposure · snapshot ${summary?.net_worth_snapshot_as_of?.slice(0, 10) ?? "—"}`}
            items={geographyPieItems}
            totalLabel={formatMoney(stockCurrentTotal)}
            formatMoney={formatMoney}
            ariaLabel="Stock geography exposure pie chart"
          />

          <ExposurePieCard
            title="Platform Breakdown"
            subtitle="Stock exposure by broker/platform"
            items={platformPieItems}
            totalLabel={formatMoney(stockCurrentTotal)}
            formatMoney={formatMoney}
            ariaLabel="Stock platform exposure pie chart"
          />

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
