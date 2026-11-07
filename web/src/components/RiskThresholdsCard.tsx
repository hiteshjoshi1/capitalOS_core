import { useId, useState, type FormEvent } from "react";

import { api, type RiskThresholdsSetting } from "../lib/api";
import { formatPercent } from "../lib/format";
import { DEFAULT_RISK_THRESHOLDS, RISK_THRESHOLDS_RESOURCE_KEY, type RiskThresholds } from "../lib/risk";
import { loadApiResource, useApiResource } from "../lib/useApiResource";

type FieldKey = keyof RiskThresholdsSetting;

const FIELDS: Array<{ key: FieldKey; defaultKey: keyof RiskThresholds; label: string; hint: string }> = [
  {
    key: "largest_position_warn_pct",
    defaultKey: "largestPositionWarnPct",
    label: "Largest position",
    hint: "One holding's share of net worth.",
  },
  {
    key: "top_n_warn_pct",
    defaultKey: "topNWarnPct",
    label: "Top 3 / top 5 positions",
    hint: "The largest positions together, as a share of net worth.",
  },
  {
    key: "platform_warn_pct",
    defaultKey: "platformWarnPct",
    label: "One platform",
    hint: "The largest platform's share of gross assets.",
  },
];

type Draft = Record<FieldKey, string>;

function toDraft(setting: RiskThresholdsSetting | undefined): Draft {
  const draft = {} as Draft;
  for (const field of FIELDS) {
    const value = setting?.[field.key];
    draft[field.key] = value == null ? "" : String(value);
  }
  return draft;
}

/**
 * Settings → Risk thresholds (#253): the percent above which the Risk page calls a figure
 * concentrated. Only an upper threshold warns. A blank field keeps the default (lib/risk.ts).
 */
export default function RiskThresholdsCard() {
  const idPrefix = useId();
  const resource = useApiResource(RISK_THRESHOLDS_RESOURCE_KEY, () => api.riskThresholds());
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const shown = draft ?? toDraft(resource.data);
  const ready = resource.data !== undefined;

  async function save(payload: RiskThresholdsSetting, message: string) {
    setSaving(true);
    setError(null);
    setDone(null);
    try {
      // Stores the answer under the key the Risk page reads, so it shows the new thresholds.
      await loadApiResource(RISK_THRESHOLDS_RESOURCE_KEY, () => api.saveRiskThresholds(payload), { force: true });
      setDraft(null);
      setDone(message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the thresholds.");
    } finally {
      setSaving(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = {} as RiskThresholdsSetting;
    for (const field of FIELDS) {
      const raw = shown[field.key].trim();
      if (raw === "") {
        payload[field.key] = null;
        continue;
      }
      const value = Number(raw);
      if (!Number.isFinite(value) || value <= 0 || value > 100) {
        setError(`${field.label}: enter a percent above 0 and up to 100, or leave it blank for the default.`);
        setDone(null);
        return;
      }
      payload[field.key] = value;
    }
    void save(payload, "Saved. The Risk page uses these thresholds.");
  }

  function resetDefaults() {
    void save(
      { largest_position_warn_pct: null, top_n_warn_pct: null, platform_warn_pct: null },
      "Back to the defaults.",
    );
  }

  return (
    <form className="card placeholderCard settingsCard" onSubmit={handleSubmit} aria-label="Risk thresholds">
      <div className="cardTitle">Risk thresholds</div>
      <p className="muted">
        The Risk page flags a figure only when it is above its threshold; a lower figure is never flagged. Leave a
        field blank for the default.
      </p>

      {FIELDS.map((field) => {
        const fallback = DEFAULT_RISK_THRESHOLDS[field.defaultKey];
        return (
          <div className="field" key={field.key}>
            <label className="label" htmlFor={`${idPrefix}-${field.key}`}>
              {field.label} (%)
            </label>
            <input
              id={`${idPrefix}-${field.key}`}
              aria-describedby={`${idPrefix}-${field.key}-hint`}
              className="input"
              type="number"
              inputMode="decimal"
              step="any"
              placeholder={String(fallback)}
              value={shown[field.key]}
              disabled={!ready || saving}
              onChange={(event) => setDraft({ ...shown, [field.key]: event.target.value })}
            />
            <span className="hint" id={`${idPrefix}-${field.key}-hint`}>
              {field.hint} Default {formatPercent(fallback, { scale: "points", decimals: 0 })}.
            </span>
          </div>
        );
      })}

      <div className="settingsActions">
        <button className="btn btnPrimary" type="submit" disabled={!ready || saving}>
          {saving ? "Saving…" : "Save thresholds"}
        </button>
        <button className="btn" type="button" disabled={!ready || saving} onClick={resetDefaults}>
          Reset to defaults
        </button>
      </div>

      {resource.error && !ready ? <p className="error" role="alert">Could not load your thresholds.</p> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
      {done ? <p className="muted" role="status">{done}</p> : null}
    </form>
  );
}
