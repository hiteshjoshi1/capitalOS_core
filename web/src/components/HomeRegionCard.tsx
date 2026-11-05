import { useEffect, useMemo, useState } from "react";

import { useBaseCurrency } from "../context/CurrencyContext";
import { api, type UserPreferences } from "../lib/api";
import { CURRENCY_OPTIONS } from "../lib/format";
import { browserTimezone, timezoneOptions } from "../lib/timezone";

/**
 * Settings → Timezone and currency (#202): the home timezone months follow, and the
 * base currency (saved on the server, so every device shows the same).
 */
export default function HomeRegionCard() {
  const [baseCurrency, chooseBaseCurrency] = useBaseCurrency();
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getPreferences().then(
      (p) => {
        if (!cancelled) setPrefs(p);
      },
      () => {
        if (!cancelled) setError("Could not load your timezone.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const current = prefs?.timezone ?? null;
  const options = useMemo(() => timezoneOptions(current), [current]);
  const device = browserTimezone();

  async function saveTimezone(zone: string) {
    if (!zone || zone === current) return;
    setSaving(true);
    setError(null);
    setDone(null);
    try {
      const next = await api.patchPreferences({ timezone: zone });
      setPrefs(next);
      setDone(`Saved. Months now follow ${next.timezone ?? zone}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the timezone.");
    } finally {
      setSaving(false);
    }
  }

  const followsApp = prefs?.timezone_source === "app" || prefs?.timezone_source === "unset";

  return (
    <div className="card placeholderCard settingsCard">
      <div className="cardTitle">Timezone and currency</div>
      <p className="muted">
        Which month is open, when a month-end snapshot is taken and History follow your home timezone. It is a
        setting, not this device&apos;s clock: travelling doesn&apos;t move your month boundaries.
      </p>

      <label className="field">
        <span className="label">Home timezone</span>
        <select
          className="input"
          value={current ?? ""}
          disabled={!prefs || saving}
          onChange={(event) => void saveTimezone(event.target.value)}
        >
          {current ? null : <option value="">Loading…</option>}
          {options.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
        {followsApp && current ? (
          <span className="hint">The app&apos;s default ({current}) until you pick one.</span>
        ) : null}
      </label>

      {device && current && device !== current ? (
        <button
          className="btn settingsThemeToggle"
          type="button"
          disabled={saving}
          onClick={() => void saveTimezone(device)}
        >
          Use this device&apos;s timezone ({device})
        </button>
      ) : null}

      <label className="field">
        <span className="label">Base currency</span>
        <select
          className="input"
          value={baseCurrency}
          onChange={(event) => chooseBaseCurrency(event.target.value)}
        >
          {CURRENCY_OPTIONS.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        <span className="hint">Saved to your account, so every device shows the same.</span>
      </label>

      {error ? <p className="error" role="alert">{error}</p> : null}
      {done ? <p className="muted" role="status">{done}</p> : null}
    </div>
  );
}
