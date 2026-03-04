import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import type { MarketDataRun } from "../lib/api";

export default function MarketData() {
  const [status, setStatus] = useState<MarketDataRun[]>([]);
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
    <div className="wrap">
      <header className="header">
        <div className="titleBlock">
          <div className="title">Market Data</div>
          <div className="subtitle">Daily stock price refresh status by exchange.</div>
        </div>
        <div className="pillRow">
          <Link className="pill" to="/">Dashboard</Link>
          <Link className="pill" to="/holdings">Stock Holdings</Link>
          <Link className="pill" to="/ingest">Ingest</Link>
          <button className="btn" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Refreshing..." : "Refresh now"}
          </button>
        </div>
      </header>

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
            <table className="table">
              <thead>
                <tr>
                  <th>Exchange</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th className="right">Requested</th>
                  <th className="right">Upserted</th>
                  <th className="right">Missing</th>
                </tr>
              </thead>
              <tbody>
                {status.map((r) => (
                  <tr key={`${r.exchange_code}-${r.id}`}>
                    <td>{r.exchange_code}</td>
                    <td>{r.provider}</td>
                    <td>{r.status}</td>
                    <td className="right">{r.requested_symbols}</td>
                    <td className="right">{r.upserted_rows}</td>
                    <td className="right">{r.missing_symbols}</td>
                  </tr>
                ))}
                {status.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">No runs yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="cardTitle">Recent Runs</div>
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
        </>
      )}
    </div>
  );
}
