import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { AccountOptions, Platform, PlatformOptions } from "../lib/api";
import "../App.css";

type LoadState = "idle" | "loading" | "ready" | "error";

type FormState = {
  name: string;
  platformId: string;
  accountType: string;
  currency: string;
  country: string;
};

const EMPTY_FORM: FormState = {
  name: "",
  platformId: "",
  accountType: "",
  currency: "",
  country: "",
};

export default function AddAccount() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [success, setSuccess] = useState<string>("");
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [options, setOptions] = useState<AccountOptions | null>(null);
  const [platformOptions, setPlatformOptions] = useState<PlatformOptions | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showPlatformForm, setShowPlatformForm] = useState<boolean>(false);
  const [showCurrencyForm, setShowCurrencyForm] = useState<boolean>(false);
  const [platformForm, setPlatformForm] = useState({
    code: "",
    name: "",
    platform_type: "",
    country: "",
    website: "",
  });
  const [currencyForm, setCurrencyForm] = useState({
    code: "",
    name: "",
  });

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [p, o, po] = await Promise.all([
          api.platforms(),
          api.accountOptions(),
          api.platformOptions(),
        ]);
        setPlatforms(p);
        setOptions(o);
        setPlatformOptions(po);
        setState("ready");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setErr(msg);
        setState("error");
      }
    })();
  }, []);

  const selectedPlatform = useMemo(() => {
    const id = Number(form.platformId);
    return platforms.find((p) => p.id === id);
  }, [form.platformId, platforms]);

  const currencyPattern = options?.currency_pattern ?? "^[A-Z]{3}$";
  const currencyRegex = useMemo(() => new RegExp(currencyPattern), [currencyPattern]);
  const currencyOptions = options?.currencies ?? [];
  const accountTypes = options?.account_types ?? [];
  const platformTypes = platformOptions?.platform_types ?? [];
  const platformCountries = platformOptions?.countries ?? [];

  useEffect(() => {
    if (selectedPlatform) {
      setForm((prev) => ({
        ...prev,
        country: selectedPlatform.country ?? "",
      }));
    }
  }, [selectedPlatform]);

  const canSubmit =
    form.name.trim().length > 0 &&
    form.platformId !== "" &&
    form.accountType !== "" &&
    form.currency.trim().length > 0 &&
    currencyRegex.test(form.currency.trim().toUpperCase());

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSuccess("");

    if (!selectedPlatform) {
      setErr("Select a platform.");
      return;
    }

    if (!canSubmit) {
      setErr("Fill all required fields with valid values.");
      return;
    }

    setErr("");
    setSaving(true);
    try {
      await api.createAccount({
        name: form.name.trim(),
        platform_id: selectedPlatform.id,
        platform: selectedPlatform.code,
        account_type: form.accountType,
        currency: form.currency.trim().toUpperCase(),
        country: selectedPlatform.country ?? null,
      });
      setSuccess("Account created.");
      setForm(EMPTY_FORM);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setSaving(false);
    }
  }

  async function refreshOptions() {
    const [p, o, po] = await Promise.all([
      api.platforms(),
      api.accountOptions(),
      api.platformOptions(),
    ]);
    setPlatforms(p);
    setOptions(o);
    setPlatformOptions(po);
  }

  async function onCreatePlatform(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr("");
    const code = platformForm.code.trim().toUpperCase();
    const name = platformForm.name.trim();
    const platform_type = platformForm.platform_type;
    const country = platformForm.country.trim().toUpperCase();

    if (!code || !name || !platform_type || !country) {
      setErr("Fill all platform fields.");
      return;
    }

    await api.createPlatform({
      code,
      name,
      platform_type,
      country,
      website: platformForm.website.trim() || null,
    });
    await refreshOptions();
    setPlatformForm({
      code: "",
      name: "",
      platform_type: "",
      country: "",
      website: "",
    });
    setShowPlatformForm(false);
  }

  async function onCreateCurrency(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr("");
    const code = currencyForm.code.trim().toUpperCase();
    if (!currencyRegex.test(code)) {
      setErr("Currency must be a 3-letter ISO code.");
      return;
    }
    await api.createCurrency({
      code,
      name: currencyForm.name.trim() || null,
    });
    await refreshOptions();
    setCurrencyForm({ code: "", name: "" });
    setShowCurrencyForm(false);
  }

  return (
    <div className="wrap">
      <header className="header">
        <div>
          <div className="title">Add Account</div>
          <div className="subtitle">Create a new account linked to a platform.</div>
        </div>
        <div className="pillRow">
          <Link className="btn" to="/">Back to dashboard</Link>
        </div>
      </header>

      {state === "loading" && <div className="card">Loading…</div>}

      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">Load error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <div className="card">
          <div className="cardTitle">Account Details</div>
          <form className="formGrid" onSubmit={onSubmit}>
            <label className="field">
              <span className="label">Name</span>
              <input
                className="input"
                type="text"
                value={form.name}
                aria-label="Account Name"
                onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="e.g. DBS Savings"
                required
              />
            </label>

            <label className="field">
              <span className="label">Platform</span>
              <select
                className="input"
                value={form.platformId}
                aria-label="Account Platform"
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    platformId: e.target.value,
                  }))
                }
                required
              >
                <option value="" disabled>
                  Select platform
                </option>
                {platforms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.code})
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn"
                onClick={() => setShowPlatformForm((prev) => !prev)}
              >
                Add platform
              </button>
            </label>

            <label className="field">
              <span className="label">Account Type</span>
              <select
                className="input"
                value={form.accountType}
                aria-label="Account Type"
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    accountType: e.target.value,
                  }))
                }
                required
              >
                <option value="" disabled>
                  Select type
                </option>
                {accountTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="label">Currency</span>
              {currencyOptions.length > 0 ? (
                <select
                  className="input"
                  value={form.currency}
                  aria-label="Account Currency"
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      currency: e.target.value,
                    }))
                  }
                  required
                >
                  <option value="" disabled>
                    Select currency
                  </option>
                  {currencyOptions.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="input"
                  type="text"
                  value={form.currency}
                  aria-label="Account Currency"
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      currency: e.target.value.toUpperCase(),
                    }))
                  }
                  placeholder="e.g. SGD"
                  required
                />
              )}
              <button
                type="button"
                className="btn"
                onClick={() => setShowCurrencyForm((prev) => !prev)}
              >
                Add currency
              </button>
              <span className="hint">Format: 3-letter ISO code.</span>
            </label>

            <label className="field">
              <span className="label">Country</span>
              <input className="input" type="text" value={form.country} aria-label="Account Country" readOnly />
            </label>


            <div className="actions">
              <button className="btn" type="submit" disabled={!canSubmit || saving}>
                {saving ? "Saving…" : "Create account"}
              </button>
              <Link className="btn" to="/">Cancel</Link>
            </div>

            {err && (
              <div className="hint" role="alert">
                {err}
              </div>
            )}
            {success && (
              <div className="hint" role="status">
                {success}
              </div>
            )}
          </form>

          {showPlatformForm && (
            <div className="card">
              <div className="cardTitle">New Platform</div>
              <form className="formGrid" onSubmit={onCreatePlatform}>
                <label className="field">
                  <span className="label">Code</span>
                  <input
                    className="input"
                    type="text"
                    value={platformForm.code}
                    aria-label="Platform Code"
                    onChange={(e) => setPlatformForm((prev) => ({ ...prev, code: e.target.value }))}
                    placeholder="e.g. DBS"
                    required
                  />
                </label>
                <label className="field">
                  <span className="label">Name</span>
                  <input
                    className="input"
                    type="text"
                    value={platformForm.name}
                    aria-label="Platform Name"
                    onChange={(e) => setPlatformForm((prev) => ({ ...prev, name: e.target.value }))}
                    placeholder="e.g. DBS Bank"
                    required
                  />
                </label>
                <label className="field">
                  <span className="label">Platform Type</span>
                  <select
                    className="input"
                    value={platformForm.platform_type}
                    aria-label="Platform Type"
                    onChange={(e) =>
                      setPlatformForm((prev) => ({ ...prev, platform_type: e.target.value }))
                    }
                    required
                  >
                    <option value="" disabled>
                      Select type
                    </option>
                    {platformTypes.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="label">Country</span>
                  {platformCountries.length > 0 ? (
                    <select
                      className="input"
                      value={platformForm.country}
                      aria-label="Platform Country"
                      onChange={(e) =>
                        setPlatformForm((prev) => ({ ...prev, country: e.target.value }))
                      }
                      required
                    >
                      <option value="" disabled>
                        Select country
                      </option>
                      {platformCountries.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="input"
                      type="text"
                      value={platformForm.country}
                      aria-label="Platform Country"
                      onChange={(e) => setPlatformForm((prev) => ({ ...prev, country: e.target.value }))}
                      placeholder="e.g. SG"
                      required
                    />
                  )}
                </label>
                <label className="field">
                  <span className="label">Website</span>
                  <input
                    className="input"
                    type="url"
                    value={platformForm.website}
                    aria-label="Platform Website"
                    onChange={(e) => setPlatformForm((prev) => ({ ...prev, website: e.target.value }))}
                    placeholder="https://www.example.com"
                  />
                </label>
                <div className="actions">
                  <button className="btn" type="submit">
                    Save platform
                  </button>
                  <button className="btn" type="button" onClick={() => setShowPlatformForm(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}

          {showCurrencyForm && (
            <div className="card">
              <div className="cardTitle">New Currency</div>
              <form className="formGrid" onSubmit={onCreateCurrency}>
                <label className="field">
                  <span className="label">Code</span>
                  <input
                    className="input"
                    type="text"
                    value={currencyForm.code}
                    aria-label="Currency Code"
                    onChange={(e) => setCurrencyForm((prev) => ({ ...prev, code: e.target.value }))}
                    placeholder="e.g. SGD"
                    required
                  />
                </label>
                <label className="field">
                  <span className="label">Name</span>
                  <input
                    className="input"
                    type="text"
                    value={currencyForm.name}
                    aria-label="Currency Name"
                    onChange={(e) => setCurrencyForm((prev) => ({ ...prev, name: e.target.value }))}
                    placeholder="e.g. Singapore Dollar"
                  />
                </label>
                <div className="actions">
                  <button className="btn" type="submit">
                    Save currency
                  </button>
                  <button className="btn" type="button" onClick={() => setShowCurrencyForm(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
