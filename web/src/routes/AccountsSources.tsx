import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import type { Account, DataHubSummary, SourceFreshness } from "../lib/api";
import { loadApiResource, useApiResource } from "../lib/useApiResource";
import * as fmt from "../lib/format";
import { DEFAULT_CADENCES, SOURCE_FRESHNESS_KEY, accountIdOf, cadenceLabel, dueLabel, statusLabel, statusTone } from "../lib/sourceFreshness";
import {
  availableFilters,
  buildSourceRows,
  filterSourceRows,
  type SourceAction,
  type SourceRowModel,
  type SourceType,
} from "../lib/sources";
import { useAuth } from "../context/useAuth";
import { useBaseCurrency } from "../context/CurrencyContext";
import PageShell from "../components/PageShell";
import LoadError from "../components/LoadError";
import StatusPill from "../components/StatusPill";
import AccountCloseControl from "../components/AccountCloseControl";
import { CadenceEditor } from "../components/SourceFreshnessTable";
import "../App.css";
import "./OperationsInbox.css";
import "./AccountsSources.css";

/**
 * Data Hub → Accounts & sources (#318, #309 mock-up B): every account, wallet, quote feed
 * and FX source in one list. Each row: status, last data, next due, ONE primary action
 * (Upload / Refresh / Fix / Fetch past) and a ⋯ menu (cadence, close or reopen, details).
 * Replaces the freshness table, the Linked accounts list and the Connected wallets list.
 */
export default function AccountsSources() {
  const freshness = useApiResource<SourceFreshness>(SOURCE_FRESHNESS_KEY, () => api.sourceFreshness());
  const summary = useApiResource<DataHubSummary>("dataHubSummary", () => api.dataHubSummary());
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [filter, setFilter] = useState<"all" | SourceType>("all");
  const [search, setSearch] = useState("");
  const { user } = useAuth();
  const isAdmin = user?.is_admin === true;

  useEffect(() => {
    loadApiResource("accounts", () => api.accounts())
      .then(setAccounts)
      .catch(() => undefined);
  }, []);

  const reloadAccounts = async () => {
    const next = await loadApiResource("accounts", () => api.accounts(), { force: true });
    setAccounts(next);
  };

  const rows = freshness.data
    ? buildSourceRows(freshness.data.sources, accounts, summary.data?.market_data.unpriced_holdings ?? [])
    : [];
  const filters = availableFilters(rows);
  const shown = filterSourceRows(rows, filter, search);
  const needYou = rows.filter((r) => !r.closed && (r.freshness.overdue || r.unpriced > 0)).length;

  const addMenu = (
    <details className="inboxRefreshMenu sourcesAddMenu">
      <summary className="btn btnPrimary inboxRefreshMenuToggle">+ Add ▾</summary>
      <div className="inboxRefreshMenuPanel" role="group" aria-label="Add">
        <Link className="inboxRefreshMenuItem" to="/accounts/new">Account</Link>
        <Link className="inboxRefreshMenuItem" to="/crypto">Wallet</Link>
        <Link className="inboxRefreshMenuItem" to="/ingest">Statement upload</Link>
      </div>
    </details>
  );

  return (
    <PageShell
      title="Accounts & sources"
      subtitle="Every account, wallet and feed, with its next step."
      headerActions={addMenu}
    >
      {freshness.isLoading && !freshness.data && <div className="card" role="status">Loading…</div>}
      {freshness.error && !freshness.data && (
        <LoadError title="Couldn't load your sources" error={freshness.error.message} onRetry={() => void freshness.reload()} />
      )}

      {freshness.data && (
        <div className="sourcesLayout">
          <div className="sourcesToolbar">
            <div className="ccFilterRail sourcesFilters" role="group" aria-label="Filter by type">
              {filters.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className="ccFilterPill"
                  aria-pressed={filter === f.key}
                  onClick={() => setFilter(f.key)}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <input
              className="input sourcesSearch"
              type="search"
              placeholder="Search…"
              aria-label="Search sources"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <p className="muted sourcesSummary" role="status">
            {rows.length === 0
              ? "No sources yet. Add an account or connect a wallet."
              : needYou === 0
                ? `All ${rows.filter((r) => !r.closed).length} sources are up to date.`
                : `${needYou} need you · ${rows.filter((r) => !r.closed).length - needYou} up to date.`}
          </p>

          {shown.length === 0 && rows.length > 0 ? (
            <p className="card muted">Nothing matches. Clear the search or pick another type.</p>
          ) : (
            <ul className="sourcesList">
              {shown.map((row) => (
                <SourceRow
                  key={row.key}
                  row={row}
                  isAdmin={isAdmin}
                  cadences={freshness.data?.cadences?.length ? freshness.data.cadences : DEFAULT_CADENCES}
                  reloadFreshness={() => freshness.reload()}
                  reloadAccounts={reloadAccounts}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </PageShell>
  );
}

type RunState = { status: "idle" | "running" | "done" | "error"; message: string };

function SourceRow({
  row,
  isAdmin,
  cadences,
  reloadFreshness,
  reloadAccounts,
}: {
  row: SourceRowModel;
  isAdmin: boolean;
  cadences: string[];
  reloadFreshness: () => Promise<unknown>;
  reloadAccounts: () => Promise<unknown>;
}) {
  const [panel, setPanel] = useState<"none" | "cadence" | "close">("none");
  const [run, setRun] = useState<RunState>({ status: "idle", message: "" });
  const [baseCurrency] = useBaseCurrency();
  const menuRef = useRef<HTMLDetailsElement | null>(null);
  const f = row.freshness;
  const due = dueLabel(f);
  const accountId = accountIdOf(row.key);

  const openPanel = (next: "cadence" | "close") => {
    if (menuRef.current) menuRef.current.open = false;
    setPanel(next);
  };

  const runAction = async (action: Extract<SourceAction, { kind: "run" }>) => {
    setRun({ status: "running", message: "" });
    try {
      let message = "Done.";
      if (action.run === "refresh_ibkr" && action.accountId != null) {
        const result = await api.ibkrFlexImportNow(action.accountId);
        const n = ((result.counts as Record<string, number> | undefined) ?? {}).positions ?? 0;
        message = `Imported ${n} position${n === 1 ? "" : "s"}.`;
      } else if (action.run === "refresh_crypto") {
        await api.cryptoRefreshNow();
        message = "Wallet refresh queued.";
      } else if (action.run === "refresh_prices") {
        const result = await api.marketDataRefreshNow();
        const n = result.exchanges?.length ?? 0;
        message = `Refreshed ${n} exchange${n === 1 ? "" : "s"}.`;
      } else if (action.run === "fx_backfill") {
        const result = await api.fxBackfill(baseCurrency);
        message =
          result.status === "up_to_date"
            ? "Past rates already complete."
            : result.status === "failed"
              ? "The rate provider didn't answer."
              : `Fetched ${result.fetched_requests} range${result.fetched_requests === 1 ? "" : "s"}.`;
      }
      setRun({ status: "done", message });
      await reloadFreshness().catch(() => undefined);
    } catch (e: unknown) {
      setRun({ status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  let primary: React.ReactNode = null;
  const action = row.action;
  if (action?.kind === "link") {
    primary = (
      <Link className="btn sourcesAction" to={action.to}>
        {action.label}
      </Link>
    );
  } else if (action?.kind === "run") {
    primary =
      action.adminOnly && !isAdmin ? (
        <span className="muted sourcesAdminHint">Admin refreshes this</span>
      ) : (
        <button
          className="btn sourcesAction"
          type="button"
          disabled={run.status === "running"}
          onClick={() => void runAction(action)}
        >
          {run.status === "running" ? "Working…" : action.label}
        </button>
      );
  }

  return (
    <li
      className={`card sourcesRow${row.closed ? " sourcesRowClosed" : ""}${f.overdue && !row.closed ? " sourcesRowAttention" : ""}`}
      data-testid={`source-row-${row.key}`}
    >
      <div className="sourcesMain">
        <p className="sourcesName">{row.name}</p>
        <p className="sourcesMeta muted">
          {row.typeLabel}
          {row.detail ? ` · ${row.detail}` : ""}
          {row.carriedNote ? <span className="hint"> · {row.carriedNote}</span> : null}
        </p>
      </div>
      <div className="sourcesData">
        <span className="sourcesLabel muted">Last data</span>
        <span>{f.last_data_date ? fmt.formatDate(f.last_data_date) : "Never"}</span>
      </div>
      <div className="sourcesStatus">
        {row.closed ? (
          <StatusPill tone="neutral" label={`Closed ${fmt.formatDate(row.account?.closed_on ?? "")}`} />
        ) : row.unpriced > 0 ? (
          <StatusPill tone="warn" label={`${row.unpriced} unpriced`} />
        ) : (
          <StatusPill tone={statusTone(f)} label={statusLabel(f)} />
        )}
        {!row.closed && due ? <span className="sourcesMeta muted">{due}</span> : null}
      </div>
      <div className="sourcesActions">
        {primary}
        <details className="inboxRefreshMenu sourcesMore" ref={menuRef}>
          <summary className="btn inboxRefreshMenuToggle" aria-label={`More for ${row.name}`}>
            <span aria-hidden="true">⋯</span>
          </summary>
          <div className="inboxRefreshMenuPanel" role="group" aria-label={`Options for ${row.name}`}>
            {!row.closed && (
              <button type="button" className="inboxRefreshMenuItem" onClick={() => openPanel("cadence")}>
                Expected: {cadenceLabel(f.cadence, f.grace_days)}…
              </button>
            )}
            {accountId != null && (
              <Link className="inboxRefreshMenuItem" to={`/ingest?account_id=${accountId}`}>
                Upload a statement
              </Link>
            )}
            {row.account && (
              <button type="button" className="inboxRefreshMenuItem" onClick={() => openPanel("close")}>
                {row.closed ? "Reopen account…" : "Close account…"}
              </button>
            )}
            {f.kind === "crypto_wallet" && (
              <Link className="inboxRefreshMenuItem" to="/crypto">
                Wallet settings
              </Link>
            )}
            {(f.kind === "market_data" || f.kind === "fx") && (
              <Link className="inboxRefreshMenuItem" to="/market-data">
                Market data details
              </Link>
            )}
          </div>
        </details>
      </div>

      {run.status === "done" || run.status === "error" ? (
        <p className={`sourcesRunMessage${run.status === "error" ? " bad" : ""}`} role="status">
          {run.message}
        </p>
      ) : null}

      {panel === "cadence" && (
        <div className="sourcesPanel">
          <CadenceEditor
            row={f}
            cadences={cadences}
            onSaved={async () => {
              await reloadFreshness();
              setPanel("none");
            }}
            onCancel={() => setPanel("none")}
          />
        </div>
      )}
      {panel === "close" && row.account && (
        <div className="sourcesPanel">
          <AccountCloseControl
            account={row.account}
            onChanged={() => {
              void reloadAccounts().then(() => setPanel("none"));
            }}
          />
          <button type="button" className="linkBtn" onClick={() => setPanel("none")}>
            Done
          </button>
        </div>
      )}
    </li>
  );
}
