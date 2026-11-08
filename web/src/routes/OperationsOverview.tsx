import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Account, InboxAction, InboxItem } from "../lib/api";
import { loadApiResource, useApiResource } from "../lib/useApiResource";
import "../App.css";
import "./OperationsInbox.css";
import PageShell from "../components/PageShell";
import * as fmt from "../lib/format";
import LoadError from "../components/LoadError";
import { useBaseCurrency } from "../context/CurrencyContext";
import { useAuth } from "../context/useAuth";
import { INBOX_SEVERITY_LABEL, inboxItemRoute } from "../lib/inbox";

/**
 * The Data Hub Overview is the Inbox (#316, #309's review): what needs you first, each
 * with its button; what's fine in one collapsed line; the latest activity in one line.
 * "Refresh all" sits in the page header. The bell (#317) and Alerts read the same list.
 */

type RunKind = NonNullable<InboxAction["run"]>;
type RunState = { status: "idle" | "running" | "done" | "error"; message: string };
const IDLE: RunState = { status: "idle", message: "" };

function formatWhen(value?: string | null): string {
  if (!value) return "never";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return fmt.formatDate(value);
  const label = fmt.formatDateTime(value);
  return label === fmt.MISSING ? value : label;
}

export default function OperationsOverview() {
  const inbox = useApiResource("operationsInbox", () => api.operationsInbox());
  const { user } = useAuth();
  const isAdmin = user?.is_admin === true;
  const [baseCurrency] = useBaseCurrency();
  const [ibkrAccounts, setIbkrAccounts] = useState<Account[]>([]);
  const [run, setRun] = useState<RunState>(IDLE);
  const menuRef = useRef<HTMLDetailsElement | null>(null);

  useEffect(() => {
    loadApiResource("accounts", () => api.accounts())
      .then((accounts) => setIbkrAccounts(accounts.filter((a) => a.platform === "IBKR")))
      .catch(() => undefined);
  }, []);

  const runOne = async (kind: RunKind, params: Record<string, string> = {}): Promise<string> => {
    switch (kind) {
      case "refresh_prices": {
        const result = await api.marketDataRefreshNow();
        const n = result.exchanges?.length ?? 0;
        return `Prices: refreshed ${n} exchange${n === 1 ? "" : "s"}.`;
      }
      case "fx_backfill": {
        const result = await api.fxBackfill(baseCurrency);
        if (result.status === "up_to_date") return "Past exchange rates: already complete.";
        if (result.status === "failed") throw new Error("The exchange-rate provider didn't answer.");
        if (result.status === "remote_disabled") return "Past exchange rates: fetching is off on this install.";
        return `Past exchange rates: fetched ${result.fetched_requests} range${result.fetched_requests === 1 ? "" : "s"}${result.remaining_requests > 0 ? `, ${result.remaining_requests} to go` : ""}.`;
      }
      case "refresh_crypto": {
        const result = await api.cryptoRefreshNow();
        const n = (result.wallets_refreshed as number | undefined) ?? 0;
        return `Wallets: queued ${n} refresh${n === 1 ? "" : "es"}.`;
      }
      case "refresh_ibkr": {
        const ids = params.account_id ? [Number(params.account_id)] : ibkrAccounts.map((a) => a.id);
        if (ids.length === 0) throw new Error("No IBKR account is linked.");
        let positions = 0;
        for (const id of ids) {
          const result = await api.ibkrFlexImportNow(id);
          positions += ((result.counts as Record<string, number> | undefined) ?? {}).positions ?? 0;
        }
        return `IBKR: imported ${positions} position${positions === 1 ? "" : "s"}.`;
      }
    }
  };

  const runAll = async (kinds: RunKind[], params: Record<string, string> = {}) => {
    if (menuRef.current) menuRef.current.open = false;
    setRun({ status: "running", message: "" });
    const messages: string[] = [];
    let failed = false;
    for (const kind of kinds) {
      try {
        messages.push(await runOne(kind, params));
      } catch (e: unknown) {
        failed = true;
        messages.push(e instanceof Error ? e.message : String(e));
      }
    }
    setRun({ status: failed ? "error" : "done", message: messages.join(" ") });
    await inbox.reload().catch(() => undefined);
  };

  const allowedRefreshes: { kind: RunKind; label: string }[] = [
    ...(isAdmin ? [{ kind: "refresh_prices" as const, label: "Prices" }] : []),
    ...(ibkrAccounts.length > 0 ? [{ kind: "refresh_ibkr" as const, label: "IBKR" }] : []),
    { kind: "refresh_crypto", label: "Crypto wallets" },
    ...(isAdmin ? [{ kind: "fx_backfill" as const, label: "Past exchange rates" }] : []),
  ];

  const refreshAll = (
    <div className="inboxRefresh">
      <button
        className="btn"
        type="button"
        disabled={run.status === "running"}
        onClick={() => runAll(allowedRefreshes.map((r) => r.kind))}
      >
        {run.status === "running" ? "Refreshing…" : "Refresh all"}
      </button>
      <details className="inboxRefreshMenu" ref={menuRef}>
        <summary className="btn inboxRefreshMenuToggle" aria-label="Choose what to refresh">
          <span aria-hidden="true">▾</span>
        </summary>
        <div className="inboxRefreshMenuPanel" role="group" aria-label="Refresh one source">
          {allowedRefreshes.map((r) => (
            <button
              key={r.kind}
              type="button"
              className="inboxRefreshMenuItem"
              disabled={run.status === "running"}
              onClick={() => runAll([r.kind])}
            >
              {r.label}
            </button>
          ))}
        </div>
      </details>
    </div>
  );

  const data = inbox.data;
  const items = data?.items ?? [];
  const latest = data?.recent_activity?.[0];

  return (
    <PageShell title="Data Hub" subtitle="What needs you, and what's fine." headerActions={refreshAll}>
      {run.status !== "idle" && run.status !== "running" && (
        <p className={run.status === "error" ? "inboxRunMessage bad" : "inboxRunMessage"} role="status">
          {run.message}
        </p>
      )}

      {inbox.isLoading && <div className="card" role="status">Loading…</div>}
      {inbox.error && !data && <LoadError title="Couldn't load the Data Hub" error={inbox.error.message} />}

      {data && (
        <div className="inboxLayout">
          <section aria-labelledby="inbox-needs-you">
            <h2 className="inboxHeading" id="inbox-needs-you">
              Needs you <span className="inboxCount">{items.length}</span>
            </h2>
            {items.length === 0 ? (
              <p className="card inboxEmpty" role="status">
                <span aria-hidden="true">✓ </span>Nothing needs you. Everything is up to date.
              </p>
            ) : (
              <ul className="inboxList">
                {items.map((item) => (
                  <InboxRow
                    key={item.id}
                    item={item}
                    isAdmin={isAdmin}
                    running={run.status === "running"}
                    onRun={(kind, params) => runAll([kind], params)}
                  />
                ))}
              </ul>
            )}
          </section>

          <nav className="inboxAdd" aria-label="Add data">
            <Link className="inboxAddLink" to="/ingest">Upload a statement</Link>
            <Link className="inboxAddLink" to="/accounts/new">Add an account</Link>
            <Link className="inboxAddLink" to="/crypto">Add a wallet</Link>
            <Link className="inboxAddLink" to="/market-data">Market data</Link>
          </nav>

          {data.all_good.length > 0 && (
            <details className="card inboxDetails">
              <summary>
                <span aria-hidden="true">✓ </span>All good ({data.all_good.length})
              </summary>
              <ul className="inboxGoodList">
                {data.all_good.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          )}

          {latest && (
            <details className="card inboxDetails">
              <summary>
                Latest: {latest.title} · {formatWhen(latest.occurred_at)}
              </summary>
              <ul className="inboxActivityList">
                {data.recent_activity.map((a, idx) => (
                  <li key={`${a.kind}-${idx}`}>
                    <span>{a.title}</span>
                    <span className="muted">
                      {a.meta} · {formatWhen(a.occurred_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <Link className="card inboxDetails inboxSourcesLink" to="/operations/sources">
            Every account and source, with its schedule and actions →
          </Link>
        </div>
      )}
    </PageShell>
  );
}

function InboxRow({
  item,
  isAdmin,
  running,
  onRun,
}: {
  item: InboxItem;
  isAdmin: boolean;
  running: boolean;
  onRun: (kind: RunKind, params: Record<string, string>) => void;
}) {
  const action = item.action;
  const route = inboxItemRoute(item);
  let control: React.ReactNode = null;
  if (action && action.admin_only && !isAdmin) {
    control = <span className="muted inboxAdminHint">An admin can fix this</span>;
  } else if (action?.run) {
    const kind = action.run;
    control = (
      <button className="btn" type="button" disabled={running} onClick={() => onRun(kind, action.params ?? {})}>
        {action.label}
      </button>
    );
  } else if (action && route) {
    control = (
      <Link className="btn" to={route}>
        {action.label}
      </Link>
    );
  }
  return (
    <li className={`card inboxItem inboxItem-${item.severity}`} data-testid={`inbox-item-${item.kind}`}>
      <div className="inboxItemText">
        <p className="inboxItemTitle">
          <span className={`inboxSeverity inboxSeverity-${item.severity}`}>{INBOX_SEVERITY_LABEL[item.severity]}</span>
          {item.title}
        </p>
        {item.detail && <p className="inboxItemDetail muted">{item.detail}</p>}
      </div>
      {control && <div className="inboxItemAction">{control}</div>}
    </li>
  );
}
