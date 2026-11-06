import { useId, useState } from "react";

import { api } from "../lib/api";
import type { SourceFreshness, SourceFreshnessRow } from "../lib/api";
import * as fmt from "../lib/format";
import {
  CADENCE_LABELS,
  SOURCE_FRESHNESS_KEY,
  cadenceLabel,
  dueLabel,
  graceUnit,
  sourceDetail,
  statusLabel,
  statusTone,
} from "../lib/sourceFreshness";
import { useApiResource } from "../lib/useApiResource";
import LoadError from "./LoadError";
import StatusPill from "./StatusPill";
import "./SourceFreshness.css";

const DEFAULT_CADENCES = ["daily", "weekdays", "weekly", "monthly", "quarterly", "off"];
const MAX_GRACE_DAYS = 90;

function CadenceEditor({
  row,
  cadences,
  onSaved,
  onCancel,
}: {
  row: SourceFreshnessRow;
  cadences: string[];
  onSaved: () => Promise<unknown>;
  onCancel: () => void;
}) {
  const id = useId();
  const [cadence, setCadence] = useState(row.cadence);
  const [grace, setGrace] = useState(String(row.grace_days));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const save = () => {
    const graceDays = Number(grace);
    if (!Number.isInteger(graceDays) || graceDays < 0 || graceDays > MAX_GRACE_DAYS) {
      setError(`Grace must be a whole number from 0 to ${MAX_GRACE_DAYS}.`);
      return;
    }
    void run(() => api.setSourceFreshnessCadence(row.source_key, { cadence, grace_days: cadence === "off" ? 0 : graceDays }));
  };

  return (
    <div className="sourceFreshnessEditor" role="group" aria-label={`Expected cadence for ${row.label}`}>
      <label className="field" htmlFor={`${id}-cadence`}>
        <span className="label">Expected</span>
        <select id={`${id}-cadence`} className="input" value={cadence} onChange={(e) => setCadence(e.target.value)}>
          {cadences.map((value) => (
            <option key={value} value={value}>
              {CADENCE_LABELS[value] ?? value}
            </option>
          ))}
        </select>
      </label>
      {cadence !== "off" ? (
        <label className="field" htmlFor={`${id}-grace`}>
          <span className="label">Grace ({graceUnit(cadence)})</span>
          <input
            id={`${id}-grace`}
            className="input sourceFreshnessGrace"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_GRACE_DAYS}
            value={grace}
            onChange={(e) => setGrace(e.target.value)}
          />
        </label>
      ) : null}
      <button className="btn" type="button" onClick={save} disabled={busy}>
        Save
      </button>
      {row.overridden ? (
        <button
          className="btn"
          type="button"
          onClick={() => void run(() => api.resetSourceFreshnessCadence(row.source_key))}
          disabled={busy}
        >
          Use default ({cadenceLabel(row.default_cadence, row.default_grace_days)})
        </button>
      ) : null}
      <button className="btn" type="button" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
      {error ? (
        <p className="sourceFreshnessError" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function SourceRow({
  row,
  cadences,
  editing,
  onEdit,
  onDone,
  reload,
}: {
  row: SourceFreshnessRow;
  cadences: string[];
  editing: boolean;
  onEdit: () => void;
  onDone: () => void;
  reload: () => Promise<unknown>;
}) {
  const due = dueLabel(row);
  return (
    <tr data-testid={`source-freshness-row-${row.source_key}`}>
      <td>
        <span className="sourceFreshnessName">{row.label}</span>
        <span className="sourceFreshnessMeta">{sourceDetail(row)}</span>
      </td>
      <td data-label="Last data">{row.last_data_date ? fmt.formatDate(row.last_data_date) : "Never"}</td>
      <td data-label="Expected">
        {cadenceLabel(row.cadence, row.grace_days)}
        {row.overridden ? <span className="sourceFreshnessMeta">Your setting</span> : null}
        {editing ? (
          <CadenceEditor
            row={row}
            cadences={cadences}
            onSaved={async () => {
              await reload();
              onDone();
            }}
            onCancel={onDone}
          />
        ) : (
          <button
            type="button"
            className="sourceFreshnessEditBtn"
            onClick={onEdit}
            aria-label={`Change expected cadence for ${row.label}`}
          >
            Change
          </button>
        )}
      </td>
      <td>
        <StatusPill tone={statusTone(row)} label={statusLabel(row)} />
        {due ? <span className="sourceFreshnessMeta">{due}</span> : null}
      </td>
    </tr>
  );
}

/**
 * Data Hub's per-source freshness table (#252): last data date, expected cadence and
 * whether each source is overdue, with the cadence editable per source.
 */
export default function SourceFreshnessTable() {
  const res = useApiResource<SourceFreshness>(SOURCE_FRESHNESS_KEY, () => api.sourceFreshness());
  const [editing, setEditing] = useState<string | null>(null);
  const data = res.data;
  const cadences = data?.cadences?.length ? data.cadences : DEFAULT_CADENCES;

  return (
    <section aria-labelledby="source-freshness-heading" id="source-freshness">
      <div className="coSectionHeader">
        <div>
          <p className="coEyebrow">CAN I TRUST THIS MONTH?</p>
          <h2 className="coSectionTitle" id="source-freshness-heading">
            Source freshness
          </h2>
        </div>
      </div>
      <div className="card sourceFreshnessCard" data-testid="source-freshness">
        {res.isLoading ? <p role="status">Loading…</p> : null}
        {res.error && !data ? (
          <LoadError compact title="Couldn't load source freshness" onRetry={() => void res.reload().catch(() => undefined)} />
        ) : null}
        {data ? (
          data.sources.length === 0 ? (
            <p className="muted">No data sources yet. Add an account or connect a wallet.</p>
          ) : (
            <>
              <p className="muted">
                {data.overdue_count === 0
                  ? "Every source is up to date."
                  : `${data.overdue_count} of ${data.sources.length} sources overdue.`}{" "}
                Newest data each source has given, checked against how often it should arrive.
              </p>
              <table className="sourceFreshnessTable">
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Last data</th>
                    <th scope="col">Expected</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((row) => (
                    <SourceRow
                      key={row.source_key}
                      row={row}
                      cadences={cadences}
                      editing={editing === row.source_key}
                      onEdit={() => setEditing(row.source_key)}
                      onDone={() => setEditing(null)}
                      reload={res.reload}
                    />
                  ))}
                </tbody>
              </table>
            </>
          )
        ) : null}
      </div>
    </section>
  );
}
