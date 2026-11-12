import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";
import type { MarketDataExchangeStatus, MarketDataRun, MarketDataUnpriced } from "../lib/api";
import MarketDataNeedsFix from "../components/MarketDataNeedsFix";
import { useAuth } from "../context/useAuth";
import PageShell from "../components/PageShell";
import StatusPill from "../components/StatusPill";
import "../App.css";
import "./MarketData.css";
import * as fmt from "../lib/format";
import LoadError from "../components/LoadError";

const REASON_LABELS = {
  RATE_LIMITED: "Rate limited",
  NO_TRADE_REPORTED: "No trade reported",
  PROVIDER_ERROR: "Provider error",
  INVALID_PRICE: "Invalid price",
} as const;

export default function MarketData() {
  const [status, setStatus] = useState<MarketDataExchangeStatus[]>([]);
  const [runs, setRuns] = useState<MarketDataRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [hasSetInitialExpand, setHasSetInitialExpand] = useState<boolean>(false);
  // #320: held stocks the refresh can't price, each with "Set ticker" (admins).
  const [unpriced, setUnpriced] = useState<MarketDataUnpriced>({ items: [], can_fix: false });
  const [notice, setNotice] = useState<string>("");
  const [refreshingExchange, setRefreshingExchange] = useState<string | null>(null);
  const { user } = useAuth();
  const isAdmin = user?.is_admin === true;
  const location = useLocation();
  const needsFixRef = useRef<HTMLElement | null>(null);

  const load = async () => {
    setError("");
    const [statusRes, runsRes, unpricedRes] = await Promise.all([
      api.marketDataStatus(),
      api.marketDataRuns(20),
      api.marketDataUnpriced().catch(() => ({ items: [], can_fix: false })),
    ]);
    const statusRows = statusRes.status ?? [];
    setStatus(statusRows);
    setRuns(runsRes.runs ?? []);
    setUnpriced(unpricedRes);
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

  // Data Hub's "Fix N" / Inbox "Fix ticker" links land here (#320).
  useEffect(() => {
    if (!loading && location.hash === "#needs-fix") {
      needsFixRef.current?.scrollIntoView?.({ block: "start" });
    }
  }, [loading, location.hash]);

  const onRefresh = async () => {
    try {
      setRefreshing(true);
      setNotice("");
      await api.marketDataRefreshNow();
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const onRefreshExchange = async (exchangeCode: string) => {
    try {
      setRefreshingExchange(exchangeCode);
      setNotice("");
      await api.marketDataRefreshNow(undefined, exchangeCode);
      await load();
      setNotice(`${exchangeCode} refreshed.`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshingExchange(null);
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
    >
      {/* #320: the page's own action bar, not the top bar. Refreshing is admin-only (#152). */}
      <div className="marketDataActions">
        {isAdmin ? (
          <button className="btn btnPrimary" onClick={onRefresh} disabled={refreshing || refreshingExchange !== null}>
            {refreshing ? "Refreshing…" : "Refresh all"}
          </button>
        ) : (
          <span className="muted">Quotes refresh daily; an admin can refresh them now.</span>
        )}
        {notice && <span className="muted" role="status">{notice}</span>}
      </div>

      {loading && <div className="card" role="status">Loading…</div>}
      {error && (
        <LoadError title="Couldn't load market data" error={error} />
      )}

      {!loading && !error && (
        <div className="wealthOverviewLayout">
          <div className="marketDataStatusChips">
            <StatusPill tone="good" label={`${totals.fresh} fresh`} />
            <StatusPill tone="warn" label={`${totals.stale} stale`} />
            <StatusPill tone="neutral" label={`${totals.failed} failed`} />
            <StatusPill tone="neutral" label={`${totals.deferred} deferred`} />
          </div>

          <section aria-label="Needs a fix" id="needs-fix" ref={needsFixRef}>
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">Held, but no price</p>
                <h2 className="coSectionTitle">
                  Needs a fix{unpriced.items.length > 0 ? ` (${unpriced.items.length})` : ""}
                </h2>
              </div>
            </div>
            <div className="card">
              <MarketDataNeedsFix
                items={unpriced.items}
                canFix={unpriced.can_fix}
                onSaved={(message) => {
                  setNotice(message);
                  void load();
                }}
              />
            </div>
          </section>

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
                // Exchanges with nothing held are left out (#315): nothing to refresh there.
                status.filter((exchange) => exchange.symbols.length > 0).map((exchange) => {
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
                          {isAdmin && (
                            <button
                              type="button"
                              className="btn btnSmall"
                              disabled={refreshing || refreshingExchange !== null}
                              aria-label={`Refresh ${exchange.exchange_code}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                void onRefreshExchange(exchange.exchange_code);
                              }}
                              onKeyDown={(e) => e.stopPropagation()}
                            >
                              {refreshingExchange === exchange.exchange_code ? "Refreshing…" : "Refresh"}
                            </button>
                          )}
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
                                {fmt.formatDate(item.latest_trade_date?.slice(0, 10))} · {item.provider ?? item.source ?? "—"}
                              </span>
                              {/* A reason only where there's a problem (#315). */}
                              {item.freshness_status !== "fresh" ? (
                                <span className="muted">
                                  {item.reason_code ? REASON_LABELS[item.reason_code] : item.failure_reason ?? "Reason unavailable"}
                                </span>
                              ) : null}
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
                          <td className="muted marketDataRunStarted">{fmt.formatDateTime(r.started_at)}</td>
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
