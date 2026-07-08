import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { MarketDataExchangeStatus, MarketDataRun } from "../lib/api";
import PageShell from "../components/PageShell";
import "../App.css";

export default function MarketData() {
  const [status, setStatus] = useState<MarketDataExchangeStatus[]>([]);
  const [runs, setRuns] = useState<MarketDataRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  const load = async () => {
    setError("");
    const [statusRes, runsRes] = await Promise.all([api.marketDataStatus(), api.marketDataRuns(20)]);
    setStatus(statusRes.status ?? []);
    setRuns(runsRes.runs ?? []);
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

  return (
    <PageShell
      title="Market Data"
      subtitle="Daily stock price refresh status by exchange."
      activeRoute="/market-data"
      headerActions={(
        <button className="btn" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing..." : "Refresh now"}
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
        <>
          <div className="card">
            <div className="cardTitle">Latest by Exchange</div>
            {status.length === 0 ? (
              <div className="muted">No runs yet.</div>
            ) : (
              <div className="grid g-mid">
                {status.map((exchange) => (
                  <div className="card" key={exchange.exchange_code}>
                    <div className="stockHoldingsHeader">
                      <h2>{exchange.exchange_code}</h2>
                      <div className="muted stockHoldingsMeta">
                        {exchange.provider ?? "—"} · {exchange.status ?? "idle"}
                      </div>
                    </div>
                    <div className="split">
                      <div className="mini">
                        <h3>Fresh</h3>
                        <div className="big small">{exchange.diagnostics_summary.fresh}</div>
                      </div>
                      <div className="mini">
                        <h3>Stale</h3>
                        <div className="big small">{exchange.diagnostics_summary.stale}</div>
                      </div>
                      <div className="mini">
                        <h3>Failed</h3>
                        <div className="big small">{exchange.diagnostics_summary.failed}</div>
                      </div>
                      <div className="mini">
                        <h3>Deferred</h3>
                        <div className="big small">{exchange.diagnostics_summary.deferred}</div>
                      </div>
                    </div>
                    <div className="tableWrap">
                    <table className="table" style={{ marginTop: 12 }}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Status</th>
                          <th>Trade date</th>
                          <th>Source</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {exchange.symbols.slice(0, 8).map((item) => (
                          <tr key={`${exchange.exchange_code}-${item.asset_id}`}>
                            <td>{item.symbol}</td>
                            <td>{item.refresh_status} / {item.freshness_status}</td>
                            <td>{item.latest_trade_date?.slice(0, 10) ?? "—"}</td>
                            <td>{item.provider ?? item.source ?? "—"}</td>
                            <td>{item.failure_reason ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <div className="cardTitle">Recent Runs</div>
            <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Exchange</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th className="right">Requested</th>
                  <th className="right">Upserted</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td className="muted">{r.started_at ?? "—"}</td>
                    <td>{r.exchange_code}</td>
                    <td>{r.provider}</td>
                    <td>{r.status}</td>
                    <td className="right">{r.requested_symbols}</td>
                    <td className="right">{r.upserted_rows}</td>
                  </tr>
                ))}
                {runs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">No runs yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}
