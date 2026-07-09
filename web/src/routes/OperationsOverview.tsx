import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { DataHubSummary } from "../lib/api";
import "../App.css";
import DirectoryListRow from "../components/DirectoryListRow";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

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

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const data = await api.dataHubSummary();
        setSummary(data);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, []);

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
