import { useState } from "react";

import { api } from "../lib/api";
import type { Account } from "../lib/api";

function todayIso(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Close an account on a date, or reopen it (#207). A closed account counts up to
 * its close date and contributes nothing to later months. */
export default function AccountCloseControl({ account, onChanged }: { account: Account; onChanged: (a: Account) => void }) {
  const [editing, setEditing] = useState(false);
  const [closedOn, setClosedOn] = useState<string>(todayIso());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save(value: string | null) {
    setBusy(true);
    setError("");
    try {
      onChanged(await api.updateAccount(account.id, { closed_on: value }));
      setEditing(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (account.closed_on) {
    return (
      <span className="accountCloseControl">
        <span className="statusPill statusPill--neutral">Closed {account.closed_on}</span>
        <button type="button" className="linkBtn" disabled={busy} onClick={() => save(null)}>
          Reopen
        </button>
        {error && <span className="hint" role="alert">{error}</span>}
      </span>
    );
  }
  if (editing) {
    return (
      <span className="accountCloseControl">
        <input
          className="input"
          type="date"
          value={closedOn}
          max={todayIso()}
          aria-label={`Close date for ${account.name}`}
          onChange={(e) => setClosedOn(e.target.value)}
        />
        <button type="button" className="btn" disabled={busy || !closedOn} onClick={() => save(closedOn)}>
          {busy ? "Saving…" : "Close account"}
        </button>
        <button type="button" className="linkBtn" disabled={busy} onClick={() => setEditing(false)}>
          Cancel
        </button>
        {error && <span className="hint" role="alert">{error}</span>}
      </span>
    );
  }
  return (
    <span className="accountCloseControl">
      <span className="statusPill statusPill--good">Active</span>
      <button type="button" className="btn btnSmall" onClick={() => setEditing(true)} aria-label={`Close ${account.name}`}>
        Close account…
      </button>
    </span>
  );
}
