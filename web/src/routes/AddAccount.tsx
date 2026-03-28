import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { AccountOptions, Currency, Platform, PlatformOptions } from "../lib/api";
import "../App.css";
import PageShell from "../components/PageShell";
import PlatformDetailsForm, { type PlatformDraft } from "../components/PlatformDetailsForm";

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
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showPlatformForm, setShowPlatformForm] = useState<boolean>(false);
  const [platformForm, setPlatformForm] = useState<PlatformDraft>({
    code: "",
    name: "",
    platform_type: "",
    country: "",
    website: "",
  });
  const [currencySearch, setCurrencySearch] = useState<string>("");
  const [countrySearch, setCountrySearch] = useState<string>("");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [p, o, po, c] = await Promise.all([
          api.platforms(),
          api.accountOptions(),
          api.platformOptions(),
          api.currencies(),
        ]);
        setPlatforms(p);
        setOptions(o);
        setPlatformOptions(po);
        setCurrencies(c);
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

  const currencyOptions = currencies;
  const accountTypes = options?.account_types ?? [];
  const platformTypes = platformOptions?.platform_types ?? [];
  const platformCountries = platformOptions?.countries ?? [];

  useEffect(() => {
    if (selectedPlatform) {
      setForm((prev) => ({
        ...prev,
        country: selectedPlatform.country ?? "",
      }));
      setCountrySearch(selectedPlatform.country ?? "");
    }
  }, [selectedPlatform]);

  const canSubmit =
    form.name.trim().length > 0 &&
    form.platformId !== "" &&
    form.accountType !== "" &&
    form.currency.trim().length > 0 &&
    form.country.trim().length > 0;

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
        country: form.country.trim().toUpperCase() || null,
      });
      setSuccess("Account created.");
      setForm(EMPTY_FORM);
      setCurrencySearch("");
      setCountrySearch("");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setSaving(false);
    }
  }

  async function refreshOptions() {
    const [p, o, po, c] = await Promise.all([
      api.platforms(),
      api.accountOptions(),
      api.platformOptions(),
      api.currencies(),
    ]);
    setPlatforms(p);
    setOptions(o);
    setPlatformOptions(po);
    setCurrencies(c);
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

  const filteredCurrencies = useMemo(() => {
    const q = currencySearch.trim().toUpperCase();
    if (!q) return currencyOptions;
    return currencyOptions.filter(
      (c) =>
        c.code.includes(q) ||
        (c.name ? c.name.toUpperCase().includes(q) : false) ||
        (c.country ? c.country.toUpperCase().includes(q) : false)
    );
  }, [currencyOptions, currencySearch]);

  const filteredCountries = useMemo(() => {
    const countries = options?.countries ?? [];
    const q = countrySearch.trim().toUpperCase();
    if (!q) return countries;
    return countries.filter((country) => country.toUpperCase().includes(q));
  }, [options?.countries, countrySearch]);

  return (
    <PageShell
      title="Add Account"
      subtitle="Create a new account linked to a platform."
      activeRoute="/accounts/new"
    >
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
              <span className="label">
                Platform
                <button
                  type="button"
                  className="linkBtn"
                  onClick={() => setShowPlatformForm(true)}
                >
                  Add platform
                </button>
              </span>
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
              <input
                className="input"
                type="text"
                list="currency-options"
                value={currencySearch}
                aria-label="Account Currency"
                onChange={(e) => {
                  const next = e.target.value.toUpperCase();
                  setCurrencySearch(next);
                  setForm((prev) => ({ ...prev, currency: next }));
                }}
                placeholder="Start typing to filter"
                required
              />
              <datalist id="currency-options">
                {filteredCurrencies.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name ?? "Unknown"} ({c.country ?? "Unknown"})
                  </option>
                ))}
              </datalist>
              <span className="hint">Type to filter and select a currency.</span>
            </label>

            <label className="field">
              <span className="label">Country</span>
              <input
                className="input"
                type="text"
                list="country-options"
                value={countrySearch}
                aria-label="Account Country"
                onChange={(e) => {
                  const next = e.target.value.toUpperCase();
                  setCountrySearch(next);
                  setForm((prev) => ({ ...prev, country: next }));
                }}
                placeholder="Start typing to filter"
                required
              />
              <datalist id="country-options">
                {filteredCountries.map((country) => (
                  <option key={country} value={country} />
                ))}
              </datalist>
              <span className="hint">Type to filter and select a country.</span>
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
            <div className="modalBackdrop" role="dialog" aria-modal="true">
              <div className="modal">
                <div className="cardTitle">New Platform</div>
                <PlatformDetailsForm
                  value={platformForm}
                  platformTypes={platformTypes}
                  platformCountries={platformCountries}
                  onChange={setPlatformForm}
                  onSubmit={onCreatePlatform}
                  onCancel={() => setShowPlatformForm(false)}
                  submitLabel="Save platform"
                />
              </div>
            </div>
          )}

        </div>
      )}
    </PageShell>
  );
}
