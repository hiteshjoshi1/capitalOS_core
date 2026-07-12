import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { MarketDataExchangeStatus, MarketDataRun } from "../lib/api";
import PageShell from "../components/PageShell";
import StatusPill from "../components/StatusPill";
import "../App.css";

const REASON_LABELS = {
  RATE_LIMITED: "Rate limited",
  NO_TRADE_REPORTED: "No trade reported",
  PROVIDER_ERROR: "Provider error",
  INVALID_PRICE: "Invalid price",
} as const;

function formatRunStarted(ts?: string | null): string {
  if (!ts) return "—";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function MarketData() {
  const [status, setStatus] = useState<MarketDataExchangeStatus[]>([]);
  const [runs, setRuns] = useState<MarketDataRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [hasSetInitialExpand, setHasSetInitialExpand] = useState<boolean>(false);

  const load = async () => {
    setError("");
    const [statusRes, runsRes] = await Promise.all([api.marketDataStatus(), api.marketDataRuns(20)]);
    const statusRows = statusRes.status ?? [];
    setStatus(statusRows);
    setRuns(runsRes.runs ?? []);
    if (!hasSetInitialExpand && statusRows.length > 0) {
      setExpanded({ [statusRows[0].exchange_code]: true });
      setHasSetInitialExpand(true);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        await load();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onRefresh = async () => {
    try {
      setRefreshing(true);
      await api.marketDataRefreshNow();
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  function toggleExpand(exchangeCode: string) {
    setExpanded((current) => ({ ...current, [exchangeCode]: !current[exchangeCode] }));
  }

  const totals = status.reduce(
    (acc, ex) => ({
      fresh: acc.fresh + (ex.diagnostics_summary?.fresh ?? 0),
      stale: acc.stale + (ex.diagnostics_summary?.stale ?? 0),
      failed: acc.failed + (ex.diagnostics_summary?.failed ?? 0),
      deferred: acc.deferred + (ex.diagnostics_summary?.deferred ?? 0),
    }),
    { fresh: 0, stale: 0, failed: 0, deferred: 0 },
  );

  return (
    <PageShell
      title="Market Data"
      subtitle="Daily quote refresh status by exchange."
      headerActions={(
        <button className="btn" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh all quotes"}
        </button>
      )}
    >
      {loading && <div className="card">Loading…</div>}
      {error && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{error}</pre>
        </div>
      )}

      {!loading && !error && (
        <div className="wealthOverviewLayout">
          <div className="marketDataStatusChips">
            <StatusPill tone="good" label={`${totals.fresh} fresh`} />
            <StatusPill tone="warn" label={`${totals.stale} stale`} />
            <StatusPill tone="neutral" label={`${totals.failed} failed`} />
            <StatusPill tone="neutral" label={`${totals.deferred} deferred`} />
          </div>

          <section aria-label="Latest refresh status by exchange">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">By exchange</p>
                <h2 className="coSectionTitle">Latest refresh status</h2>
              </div>
            </div>
            <div className="card">
              {status.length === 0 ? (
                <p className="muted">No runs yet.</p>
              ) : (
                status.map((exchange) => {
                  const isExpanded = !!expanded[exchange.exchange_code];
                  return (
                    <div className="marketDataExchange" key={exchange.exchange_code}>
                      <div
                        className="marketDataExchangeRow"
                        role="button"
                        tabIndex={0}
                        onClick={() => toggleExpand(exchange.exchange_code)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") toggleExpand(exchange.exchange_code);
                        }}
                      >
                        <div className="marketDataExchangeMeta">
                          <strong>{exchange.exchange_code}</strong>
                          <span className="muted">{exchange.provider ?? "—"}</span>
                          <StatusPill tone="neutral" label={exchange.status ?? "idle"} />
                        </div>
                        <div className="marketDataExchangeSummary">
                          <span className="muted">
                            {exchange.diagnostics_summary.fresh} fresh · {exchange.diagnostics_summary.stale} stale
                          </span>
                          <span className="marketDataChevron">{isExpanded ? "Hide symbols ▲" : "View symbols ▼"}</span>
                        </div>
                      </div>
                      {isExpanded && (
                        <div className="marketDataSymbolList">
                          {exchange.symbols.map((item) => (
                            <div className="marketDataSymbolRow" key={`${exchange.exchange_code}-${item.asset_id}`}>
                              <span className="marketDataSymbolCode">{item.symbol}</span>
                              <StatusPill
                                tone={item.freshness_status === "fresh" ? "good" : "warn"}
                                label={item.freshness_status === "fresh" ? "Fresh" : "Stale"}
                              />
                              <span className="muted marketDataSymbolMeta">
                                {item.latest_trade_date?.slice(0, 10) ?? "—"} · {item.provider ?? item.source ?? "—"}
                              </span>
                              <span className="muted">
                                {item.reason_code ? REASON_LABELS[item.reason_code] : item.failure_reason ?? "Reason unavailable"}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </section>

          <section aria-label="Recent runs">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">History</p>
                <h2 className="coSectionTitle">Recent runs</h2>
              </div>
            </div>
            <div className="card">
              {runs.length === 0 ? (
                <p className="muted">No runs yet.</p>
              ) : (
                <div className="marketDataRunsTableWrap">
                  <table className="marketDataRunsTable">
                    <thead>
                      <tr>
                        <th scope="col">Started</th>
                        <th scope="col">Exchange</th>
                        <th scope="col">Provider</th>
                        <th scope="col">Status</th>
                        <th scope="col">Rows</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((r) => (
                        <tr key={r.id}>
                          <td className="muted marketDataRunStarted">{formatRunStarted(r.started_at)}</td>
                          <td>
                            <strong>{r.exchange_code}</strong>
                          </td>
                          <td className="muted marketDataRunProvider">{r.provider}</td>
                          <td>
                            <StatusPill tone="neutral" label={r.status ?? "—"} />
                          </td>
                          <td className="muted marketDataRunCounts">
                            {r.requested_symbols} → {r.upserted_rows}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </PageShell>
  );
}
