import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Account, DataHubSummary } from "../lib/api";
import "../App.css";
import DirectoryListRow from "../components/DirectoryListRow";
import PageShell from "../components/PageShell";
import StatusPill from "../components/StatusPill";

type LoadState = "idle" | "loading" | "ready" | "error";
type RefreshStatus = "idle" | "running" | "done" | "error";

type RefreshRowState = {
  status: RefreshStatus;
  message: string;
};

const REFRESH_IDLE: RefreshRowState = { status: "idle", message: "" };

type QuickAction = {
  title: string;
  desc: string;
  to: string;
};

const QUICK_ACTIONS: QuickAction[] = [
  { title: "Import Statements", desc: "Upload a new broker, bank, or card statement.", to: "/ingest" },
  { title: "Add Accounts", desc: "Create an account under a linked platform.", to: "/accounts/new" },
  { title: "Add Platforms", desc: "Register a new bank, broker, or exchange.", to: "/platforms" },
  { title: "Add Crypto Wallets", desc: "Connect and verify a wallet.", to: "/crypto" },
  { title: "Refresh Market Data", desc: "Pull the latest quotes across every exchange.", to: "/market-data" },
];

export default function OperationsOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<DataHubSummary | null>(null);
  const [ibkrAccounts, setIbkrAccounts] = useState<Account[]>([]);
  const [selectedIbkrAccountId, setSelectedIbkrAccountId] = useState<number | null>(null);

  const [priceRefresh, setPriceRefresh] = useState<RefreshRowState>(REFRESH_IDLE);
  const [ibkrRefresh, setIbkrRefresh] = useState<RefreshRowState>(REFRESH_IDLE);
  const [cryptoRefresh, setCryptoRefresh] = useState<RefreshRowState>(REFRESH_IDLE);

  const reloadSummary = async () => {
    try {
      const data = await api.dataHubSummary();
      setSummary(data);
    } catch {
      // Refresh buttons already surface their own errors — a failed reload here
      // just leaves the stat cards stale, not worth a second error banner.
    }
  };

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [data, accounts] = await Promise.all([api.dataHubSummary(), api.accounts()]);
        setSummary(data);
        const ibkr = accounts.filter((a) => a.platform === "IBKR");
        setIbkrAccounts(ibkr);
        if (ibkr.length > 0) setSelectedIbkrAccountId(ibkr[0].id);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, []);

  const runPriceRefresh = async () => {
    setPriceRefresh({ status: "running", message: "" });
    try {
      const result = await api.marketDataRefreshNow();
      const exchangeCount = result.exchanges?.length ?? 0;
      setPriceRefresh({ status: "done", message: `Refreshed ${exchangeCount} exchange${exchangeCount === 1 ? "" : "s"}.` });
      await reloadSummary();
    } catch (e: unknown) {
      setPriceRefresh({ status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const runIbkrRefresh = async () => {
    if (selectedIbkrAccountId == null) {
      setIbkrRefresh({ status: "error", message: "No IBKR account found to refresh." });
      return;
    }
    setIbkrRefresh({ status: "running", message: "" });
    try {
      const result = await api.ibkrFlexImportNow(selectedIbkrAccountId);
      const counts = (result.counts as Record<string, number> | undefined) ?? {};
      setIbkrRefresh({
        status: "done",
        message: `Imported ${counts.positions ?? 0} position${counts.positions === 1 ? "" : "s"}, ${counts.nav_snapshots ?? 0} NAV snapshot${counts.nav_snapshots === 1 ? "" : "s"}.`,
      });
      await reloadSummary();
    } catch (e: unknown) {
      setIbkrRefresh({ status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const runCryptoRefresh = async () => {
    setCryptoRefresh({ status: "running", message: "" });
    try {
      const result = await api.cryptoRefreshNow();
      const walletsRefreshed = (result.wallets_refreshed as number | undefined) ?? 0;
      setCryptoRefresh({
        status: "done",
        message: `Queued refresh for ${walletsRefreshed} wallet${walletsRefreshed === 1 ? "" : "s"}.`,
      });
      await reloadSummary();
    } catch (e: unknown) {
      setCryptoRefresh({ status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const statCards = summary
    ? [
        {
          label: "Linked accounts",
          value: String(summary.linked_accounts),
          meta: `Across ${summary.platform_count} platform${summary.platform_count === 1 ? "" : "s"} · ${summary.currency_count} currenc${summary.currency_count === 1 ? "y" : "ies"}`,
        },
        {
          label: "Import health",
          value: summary.import_health.pending_count === 0 ? "0 pending" : `${summary.import_health.pending_count} pending`,
          meta: summary.import_health.last_import_at
            ? `Last import ${summary.import_health.last_import_at} · ${summary.import_health.last_import_platform ?? "—"}`
            : "No imports yet",
        },
        {
          label: "Market data",
          value: `${summary.market_data.fresh} / ${summary.market_data.fresh + summary.market_data.stale} fresh`,
          meta: summary.market_data.stale > 0 ? `${summary.market_data.stale} stale` : "All quotes fresh",
        },
        {
          label: "Crypto wallets",
          value: `${summary.connected_wallet_count} connected`,
          meta: summary.connected_wallet_labels.length > 0 ? summary.connected_wallet_labels.join(", ") : "No wallets connected",
        },
      ]
    : [];

  return (
    <PageShell
      title="Data Hub"
      subtitle="Connections, imports, and market data health at a glance."
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
          <section aria-label="Data Hub status">
            <div className="dataHubStatGrid">
              {statCards.map((stat) => (
                <article className="card dataHubStatCard" key={stat.label}>
                  <p className="dataHubStatLabel">{stat.label}</p>
                  <p className="dataHubStatValue">{stat.value}</p>
                  <p className="dataHubStatMeta">{stat.meta}</p>
                </article>
              ))}
            </div>
          </section>

          <section aria-label="Quick actions">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">ACTIONS</p>
                <h2 className="coSectionTitle">Quick actions</h2>
              </div>
            </div>
            <div className="dataHubActionGrid">
              {QUICK_ACTIONS.map((action) => (
                <Link className="dataHubActionCard" to={action.to} key={action.to}>
                  <strong>{action.title}</strong>
                  <span>{action.desc}</span>
                </Link>
              ))}
            </div>
          </section>

          <section aria-label="Refresh data">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">DATA SOURCES</p>
                <h2 className="coSectionTitle">Refresh now</h2>
              </div>
            </div>
            <div className="dataHubActionGrid">
              <article className="card dataHubStatCard">
                <p className="dataHubStatLabel">Price refresh</p>
                <p className="muted">Pull the latest quotes across every configured exchange.</p>
                <button className="btn" type="button" onClick={runPriceRefresh} disabled={priceRefresh.status === "running"}>
                  {priceRefresh.status === "running" ? "Refreshing…" : "Refresh prices"}
                </button>
                {priceRefresh.status === "done" && <StatusPill tone="good" label={priceRefresh.message} />}
                {priceRefresh.status === "error" && <StatusPill tone="warn" label={priceRefresh.message} />}
              </article>

              <article className="card dataHubStatCard">
                <p className="dataHubStatLabel">IBKR refresh</p>
                <p className="muted">Pull the latest Flex statement (positions, NAV, cash) for your IBKR account.</p>
                {ibkrAccounts.length > 1 ? (
                  <select
                    className="coPillBtnInput"
                    aria-label="IBKR account"
                    value={selectedIbkrAccountId ?? ""}
                    onChange={(e) => setSelectedIbkrAccountId(Number(e.target.value))}
                  >
                    {ibkrAccounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                ) : null}
                <button
                  className="btn"
                  type="button"
                  onClick={runIbkrRefresh}
                  disabled={ibkrRefresh.status === "running" || ibkrAccounts.length === 0}
                  title={ibkrAccounts.length === 0 ? "No IBKR account linked" : undefined}
                >
                  {ibkrRefresh.status === "running" ? "Refreshing…" : "Refresh IBKR"}
                </button>
                {ibkrRefresh.status === "done" && <StatusPill tone="good" label={ibkrRefresh.message} />}
                {ibkrRefresh.status === "error" && <StatusPill tone="warn" label={ibkrRefresh.message} />}
              </article>

              <article className="card dataHubStatCard">
                <p className="dataHubStatLabel">Crypto refresh</p>
                <p className="muted">Queue a balance/price refresh for every connected wallet.</p>
                <button className="btn" type="button" onClick={runCryptoRefresh} disabled={cryptoRefresh.status === "running"}>
                  {cryptoRefresh.status === "running" ? "Refreshing…" : "Refresh crypto"}
                </button>
                {cryptoRefresh.status === "done" && <StatusPill tone="good" label={cryptoRefresh.message} />}
                {cryptoRefresh.status === "error" && <StatusPill tone="warn" label={cryptoRefresh.message} />}
              </article>
            </div>
          </section>

          <section aria-label="Recent activity">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">TIMELINE</p>
                <h2 className="coSectionTitle">Recent activity</h2>
              </div>
            </div>
            <div className="card">
              {summary && summary.recent_activity.length > 0 ? (
                summary.recent_activity.map((item, idx) => (
                  <DirectoryListRow
                    key={`${item.kind}-${idx}`}
                    title={item.title}
                    meta={item.meta}
                    right={item.occurred_at}
                  />
                ))
              ) : (
                <p className="muted">No recent activity yet.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </PageShell>
  );
}
