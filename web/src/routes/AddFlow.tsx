import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, UploadRefusedError } from "../lib/api";
import type { Account, AccountOptions, Platform, PlatformOptions, UploadRefusal } from "../lib/api";
import { loadApiResource } from "../lib/useApiResource";
import { useAuth } from "../context/useAuth";
import {
  STEP_LABELS,
  availableKinds,
  deriveCode,
  detailsMissing,
  draftFromPlatform,
  joinMissing,
  kindMeta,
  parseKind,
  platformMissing,
  platformsForKind,
  whereMissing,
  type AccountDraft,
  type AddKind,
  type WalletChain,
} from "../lib/addFlow";
import { dateFromFilename } from "./ingestUtils";
import PageShell from "../components/PageShell";
import LoadError from "../components/LoadError";
import StatusPill from "../components/StatusPill";
import PlatformDetailsForm, { type PlatformDraft } from "../components/PlatformDetailsForm";
import "../App.css";
import "./AddFlow.css";

// The wallet step brings the Solana stack; it loads only when a wallet is being added (#145).
const WalletConnectStep = lazy(() => import("../wallet/WalletConnectStep.tsx"));

const MOBILE_BREAKPOINT_PX = 900;

type LoadState = "loading" | "ready" | "error";

type UploadReport = {
  job_id?: number;
  status?: string;
  counts?: {
    transactions_parsed?: number;
    transactions_inserted?: number;
    positions_parsed?: number;
    canonical_positions_written?: number;
  };
};

const EMPTY_PLATFORM: PlatformDraft = { code: "", name: "", platform_type: "", country: "", website: "" };

function uploadSummary(report: UploadReport): { tone: "good" | "warn" | "neutral"; text: string } {
  const c = report.counts ?? {};
  if (report.status === "IMPORTED") {
    const holdings = c.canonical_positions_written ?? 0;
    const inserted = c.transactions_inserted ?? 0;
    const parts = [];
    if (inserted || !holdings) parts.push(`${inserted} transaction${inserted === 1 ? "" : "s"}`);
    if (holdings) parts.push(`${holdings} holding${holdings === 1 ? "" : "s"}`);
    return { tone: "good", text: `Imported: ${parts.join(" and ")} saved.` };
  }
  if (report.status === "NEEDS_MAPPING") {
    return { tone: "warn", text: "CapitalOS doesn't know this file's format yet. Open the import report to fix it." };
  }
  return { tone: "neutral", text: `Upload finished with status ${report.status ?? "unknown"}.` };
}

/**
 * "+ Add" (#319, Data Hub step 5 of 7): one flow for a bank account, card, brokerage, fund, exchange,
 * loan or self-custody wallet. What → where (platforms of the right type; add one inline) →
 * details (defaults from the platform) → first data (upload a statement, or connect and sign).
 * Replaces the Add Account form (/accounts/new) and the Add Crypto Wallets page (/crypto).
 * Buttons stay enabled: pressing one with something missing says what (no dead buttons).
 */
export default function AddFlow() {
  const [searchParams] = useSearchParams();
  const requestedKind = parseKind(searchParams.get("what"));
  const { user } = useAuth();
  const isAdmin = user?.is_admin === true;

  const [state, setState] = useState<LoadState>("loading");
  const [loadErr, setLoadErr] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [options, setOptions] = useState<AccountOptions | null>(null);
  const [platformOptions, setPlatformOptions] = useState<PlatformOptions | null>(null);

  const [step, setStep] = useState<number>(requestedKind ? 1 : 0);
  const [kind, setKind] = useState<AddKind | null>(requestedKind);
  const [platformId, setPlatformId] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [chain, setChain] = useState<WalletChain | null>(null);
  const [walletLabel, setWalletLabel] = useState("");
  const [draft, setDraft] = useState<AccountDraft>({ name: "", currency: "", country: "" });
  const [draftFor, setDraftFor] = useState<number | null>(null);
  const [blocked, setBlocked] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [account, setAccount] = useState<Account | null>(null);

  const [showPlatformForm, setShowPlatformForm] = useState(false);
  const [platformDraft, setPlatformDraft] = useState<PlatformDraft>(EMPTY_PLATFORM);
  const [platformBlocked, setPlatformBlocked] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [asOf, setAsOf] = useState("");
  const [uploading, setUploading] = useState(false);
  const [report, setReport] = useState<UploadReport | null>(null);
  const [refusal, setRefusal] = useState<UploadRefusal | null>(null);
  const [walletDone, setWalletDone] = useState("");

  const [isMobile, setIsMobile] = useState<boolean>(() => window.innerWidth <= MOBILE_BREAKPOINT_PX);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= MOBILE_BREAKPOINT_PX);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.platforms(), api.accountOptions(), api.platformOptions()])
      .then(([p, o, po]) => {
        if (cancelled) return;
        setPlatforms(p);
        setOptions(o);
        setPlatformOptions(po);
        setState("ready");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadErr(e instanceof Error ? e.message : String(e));
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Each step change moves focus to the step's heading, so keyboard and screen-reader users land on it.
  const shownStep = useRef(step);
  useEffect(() => {
    if (shownStep.current !== step) {
      shownStep.current = step;
      headingRef.current?.focus();
    }
  }, [step]);

  const meta = kindMeta(kind);
  const isWallet = meta?.accountType === null;
  const kinds = availableKinds(options?.account_types ?? []);
  const platform = platforms.find((p) => p.id === platformId) ?? null;
  const shownPlatforms = meta && !isWallet ? platformsForKind(platforms, meta, showAll) : [];
  const hiddenCount = meta && !isWallet ? platforms.length - platformsForKind(platforms, meta, false).length : 0;

  function goTo(next: number) {
    setBlocked("");
    setErr("");
    setStep(next);
  }

  function chooseKind(next: AddKind) {
    setKind(next);
    setBlocked("");
    // A different kind means a different "where": start that step afresh.
    setPlatformId(null);
    setChain(null);
    setShowAll(false);
    setShowPlatformForm(false);
  }

  function choosePlatform(id: number) {
    setPlatformId(id);
    setBlocked("");
  }

  function next() {
    if (step === 0) {
      if (!meta) {
        setBlocked("To continue: choose what you're adding.");
        return;
      }
      goTo(1);
      return;
    }
    if (step === 1 && meta) {
      const missing = whereMissing(meta, platformId, chain);
      if (missing.length) {
        setBlocked(`To continue: ${joinMissing(missing)}.`);
        return;
      }
      // Defaults come from the platform; they're rebuilt only when the platform changes.
      if (platform && draftFor !== platform.id) {
        setDraft(draftFromPlatform(platform, meta));
        setDraftFor(platform.id);
      }
      goTo(2);
      return;
    }
    if (step === 2 && isWallet) goTo(3);
  }

  async function createAccount() {
    if (!meta || !platform || meta.accountType === null) return;
    const missing = detailsMissing(draft);
    if (missing.length) {
      setBlocked(`To create the account: add ${joinMissing(missing)}.`);
      return;
    }
    setBlocked("");
    setErr("");
    setSaving(true);
    try {
      const created = await api.createAccount({
        name: draft.name.trim(),
        platform_id: platform.id,
        platform: platform.code,
        account_type: meta.accountType,
        currency: draft.currency.trim().toUpperCase(),
        country: draft.country.trim().toUpperCase() || null,
      });
      setAccount(created);
      // Other pages read the cached list (#149): refresh it so they see the new account.
      await loadApiResource("accounts", () => api.accounts(), { force: true }).catch(() => undefined);
      goTo(3);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function openPlatformForm() {
    setPlatformDraft({
      ...EMPTY_PLATFORM,
      platform_type: meta?.platformTypes[0] ?? "",
      country: platformOptions?.countries.includes("SG") ? "SG" : "",
    });
    setPlatformBlocked("");
    setShowPlatformForm(true);
  }

  function onPlatformDraftChange(nextDraft: PlatformDraft) {
    // The code follows the name until it's edited by hand ("DBS Bank" → DBS_BANK).
    const codeFollows = platformDraft.code === deriveCode(platformDraft.name);
    setPlatformDraft(
      codeFollows && nextDraft.code === platformDraft.code ? { ...nextDraft, code: deriveCode(nextDraft.name) } : nextDraft,
    );
  }

  async function onCreatePlatform(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const missing = platformMissing(platformDraft);
    if (missing.length) {
      setPlatformBlocked(`To add the platform: ${joinMissing(missing)}.`);
      return;
    }
    setPlatformBlocked("");
    try {
      const created = await api.createPlatform({
        code: platformDraft.code.trim().toUpperCase(),
        name: platformDraft.name.trim(),
        platform_type: platformDraft.platform_type,
        country: platformDraft.country.trim().toUpperCase(),
        website: platformDraft.website.trim() || null,
      });
      setPlatforms(await api.platforms());
      setPlatformId(created.id);
      setShowPlatformForm(false);
      setBlocked("");
    } catch (error) {
      // e.g. 403 for a non-admin: platforms are shared data (#152).
      setPlatformBlocked(error instanceof Error ? error.message : "Could not add the platform.");
    }
  }

  function chooseFile(f: File | null) {
    setFile(f);
    setBlocked("");
    const fromName = dateFromFilename(f?.name);
    if (fromName) setAsOf(fromName);
  }

  async function upload(allowAccountMismatch = false) {
    if (!account) return;
    if (!file) {
      setBlocked("To upload: choose the statement file.");
      return;
    }
    setBlocked("");
    setErr("");
    setRefusal(null);
    setUploading(true);
    try {
      const result = allowAccountMismatch
        ? await api.ingestUpload(account.id, file, asOf || undefined, { allowAccountMismatch: true })
        : await api.ingestUpload(account.id, file, asOf || undefined);
      setReport(result as UploadReport);
    } catch (e: unknown) {
      if (e instanceof UploadRefusedError) setRefusal(e.refusal);
      else setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  function restart() {
    setStep(0);
    setKind(null);
    setPlatformId(null);
    setChain(null);
    setWalletLabel("");
    setDraft({ name: "", currency: "", country: "" });
    setDraftFor(null);
    setAccount(null);
    setFile(null);
    setAsOf("");
    setReport(null);
    setRefusal(null);
    setWalletDone("");
    setBlocked("");
    setErr("");
  }

  // Once the account exists, the earlier steps are done: it can't be "un-created" by going back.
  const locked = account !== null || walletDone !== "";
  const stepTitle = [
    "What are you adding?",
    isWallet ? "Which chain is the wallet on?" : "Where is it?",
    isWallet ? "Name the wallet" : "Account details",
    isWallet ? "Connect and sign" : "Add its first data",
  ][step];

  const blockedNote = blocked ? (
    <p className="addFlowBlocked" role="alert">
      {blocked}
    </p>
  ) : null;

  return (
    <PageShell title="Add" subtitle="An account, card, brokerage or wallet, and its first data, in one flow.">
      {state === "loading" && (
        <div className="card" role="status">
          Loading…
        </div>
      )}
      {state === "error" && <LoadError title="Couldn't load platforms" error={loadErr} />}

      {state === "ready" && (
        <div className="card addFlow">
          <nav aria-label="Steps">
            <ol className="addFlowSteps">
              {STEP_LABELS.map((label, i) => {
                const current = i === step;
                const done = i < step;
                return (
                  <li
                    key={label}
                    className={`addFlowStep${current ? " addFlowStepCurrent" : ""}${done ? " addFlowStepDone" : ""}`}
                    aria-current={current ? "step" : undefined}
                  >
                    {done && !locked ? (
                      <button
                        type="button"
                        className="addFlowStepBtn"
                        aria-label={`${label}: done, go back to this step`}
                        onClick={() => goTo(i)}
                      >
                        <span className="addFlowStepNum" aria-hidden="true">
                          ✓
                        </span>
                        <span>{label}</span>
                      </button>
                    ) : (
                      <span className="addFlowStepBtn">
                        <span className="addFlowStepNum" aria-hidden="true">
                          {done ? "✓" : i + 1}
                        </span>
                        <span>{label}</span>
                        {done && <span className="srOnly">: done</span>}
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </nav>

          <h2
            className="addFlowTitle"
            tabIndex={-1}
            ref={headingRef}
            aria-label={`Step ${step + 1} of ${STEP_LABELS.length}: ${stepTitle}`}
          >
            <span className="addFlowStepOf">
              Step {step + 1} of {STEP_LABELS.length}
            </span>
            <span className="addFlowTitleText">{stepTitle}</span>
          </h2>

          {step === 0 && (
            <fieldset className="addFlowChoices">
              <legend className="srOnly">What are you adding?</legend>
              {kinds.map((k) => (
                <label key={k.id} className={`addFlowChoice${kind === k.id ? " addFlowChoiceOn" : ""}`}>
                  <input type="radio" name="add-kind" value={k.id} checked={kind === k.id} onChange={() => chooseKind(k.id)} />
                  <span className="addFlowChoiceText">
                    <strong>{k.label}</strong>
                    <span className="muted">{k.hint}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          )}

          {step === 1 && meta && isWallet && (
            <fieldset className="addFlowChoices">
              <legend className="srOnly">Which chain is the wallet on?</legend>
              <label className={`addFlowChoice${chain === "evm" ? " addFlowChoiceOn" : ""}`}>
                <input type="radio" name="add-chain" value="evm" checked={chain === "evm"} onChange={() => setChain("evm")} />
                <span className="addFlowChoiceText">
                  <strong>Ethereum and EVM chains</strong>
                  <span className="muted">Ethereum, Base, Arbitrum, Optimism, Mantle, Scroll. MetaMask or similar.</span>
                </span>
              </label>
              <label className={`addFlowChoice${chain === "solana" ? " addFlowChoiceOn" : ""}`}>
                <input type="radio" name="add-chain" value="solana" checked={chain === "solana"} onChange={() => setChain("solana")} />
                <span className="addFlowChoiceText">
                  <strong>Solana</strong>
                  <span className="muted">Phantom, or a Ledger (signs an on-chain memo).</span>
                </span>
              </label>
            </fieldset>
          )}

          {step === 1 && meta && !isWallet && (
            <>
              {platforms.length === 0 ? (
                <p className="muted">No platforms yet.</p>
              ) : (
                <fieldset className="addFlowChoices addFlowPlatforms">
                  <legend className="srOnly">Where is the {meta.label.toLowerCase()}?</legend>
                  {shownPlatforms.map((p) => (
                    <label key={p.id} className={`addFlowChoice${platformId === p.id ? " addFlowChoiceOn" : ""}`}>
                      <input
                        type="radio"
                        name="add-platform"
                        value={p.id}
                        checked={platformId === p.id}
                        onChange={() => choosePlatform(p.id)}
                      />
                      <span className="addFlowChoiceText">
                        <strong>{p.name}</strong>
                        <span className="muted">
                          {p.country} · {p.platform_type.replace(/_/g, " ").toLowerCase()}
                        </span>
                      </span>
                    </label>
                  ))}
                </fieldset>
              )}
              {hiddenCount > 0 && !showAll && (
                <button type="button" className="linkBtn addFlowMore" onClick={() => setShowAll(true)}>
                  Show all platforms ({hiddenCount} more)
                </button>
              )}

              {!showPlatformForm &&
                (isAdmin ? (
                  <button type="button" className="btn btnSmall addFlowMore" onClick={openPlatformForm}>
                    Not listed? Add a platform
                  </button>
                ) : (
                  <p className="hint">Not listed? Platforms are shared: an admin adds them in Settings → Admin.</p>
                ))}

              {showPlatformForm && (
                <section className="addFlowInline" aria-label="New platform">
                  <div className="cardTitle">New platform</div>
                  <PlatformDetailsForm
                    value={platformDraft}
                    platformTypes={platformOptions?.platform_types ?? []}
                    platformCountries={platformOptions?.countries ?? []}
                    onChange={onPlatformDraftChange}
                    onSubmit={onCreatePlatform}
                    onCancel={() => setShowPlatformForm(false)}
                    submitLabel="Add platform"
                  />
                  {platformBlocked && (
                    <p className="addFlowBlocked" role="alert">
                      {platformBlocked}
                    </p>
                  )}
                </section>
              )}
            </>
          )}

          {step === 2 && meta && isWallet && (
            <div className="formGrid">
              <div className="field">
                <label className="label" htmlFor="add-wallet-name">Wallet name (optional)</label>
                <input
                  id="add-wallet-name"
                  aria-describedby="add-wallet-name-hint"
                  className="input"
                  value={walletLabel}
                  onChange={(e) => setWalletLabel(e.target.value)}
                  placeholder="e.g. Ledger cold wallet"
                />
                <span className="hint" id="add-wallet-name-hint">Shown in Accounts &amp; sources. Leave it blank to use the address.</span>
              </div>
            </div>
          )}

          {step === 2 && meta && !isWallet && platform && (
            <div className="formGrid">
              <p className="muted addFlowSummary">
                {meta.label} at <strong>{platform.name}</strong> ({platform.code})
              </p>
              <div className="field">
                <label className="label" htmlFor="add-name">Name</label>
                <input
                  id="add-name"
                  aria-describedby="add-name-hint"
                  className="input"
                  value={draft.name}
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                  required
                />
                <span className="hint" id="add-name-hint">How it shows everywhere, e.g. “Citi Rewards card”.</span>
              </div>
              <div className="split">
                <div className="field">
                  <label className="label" htmlFor="add-currency">Currency</label>
                  <input
                    id="add-currency"
                    aria-describedby="add-currency-hint"
                    className="input"
                    list="add-currency-options"
                    value={draft.currency}
                    onChange={(e) => setDraft((d) => ({ ...d, currency: e.target.value.toUpperCase() }))}
                    placeholder="e.g. SGD"
                    maxLength={3}
                    required
                  />
                  <datalist id="add-currency-options">
                    {(options?.currencies ?? []).map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                  <span className="hint" id="add-currency-hint">The statements' currency.</span>
                </div>
                <div className="field">
                  <label className="label" htmlFor="add-country">Country (optional)</label>
                  <input
                    id="add-country"
                    aria-describedby="add-country-hint"
                    className="input"
                    list="add-country-options"
                    value={draft.country}
                    onChange={(e) => setDraft((d) => ({ ...d, country: e.target.value.toUpperCase() }))}
                    placeholder={platform.country}
                    maxLength={3}
                  />
                  <datalist id="add-country-options">
                    {(options?.countries ?? []).map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                  <span className="hint" id="add-country-hint">Blank uses the platform's ({platform.country}).</span>
                </div>
              </div>
            </div>
          )}

          {step === 3 && !isWallet && account && (
            <div className="formGrid">
              <p className="addFlowDone" role="status">
                ✓ {account.name} created.
              </p>
              {report ? (
                <div className="addFlowResult">
                  <StatusPill tone={uploadSummary(report).tone} label={report.status === "IMPORTED" ? "Imported" : report.status ?? "Done"} />
                  <p>{uploadSummary(report).text}</p>
                  {report.job_id != null && <Link to={`/ingest?job=${report.job_id}`}>Open the import report</Link>}
                </div>
              ) : (
                <>
                  <div className="field">
                    <label className="label" htmlFor="add-file">Statement file</label>
                    <input
                      id="add-file"
                      aria-describedby="add-file-hint"
                      className="input"
                      type="file"
                      accept=".csv,.xls,.xlsx,.pdf,.xml"
                      onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
                    />
                    <span className="hint" id="add-file-hint">Its newest statement (.csv, .xls, .xlsx). Older ones can follow from Imports.</span>
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="add-asof">Statement date (optional)</label>
                    <input id="add-asof" aria-describedby="add-asof-hint" className="input" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
                    <span className="hint" id="add-asof-hint">Used only when the file doesn't state its own date.</span>
                  </div>
                  {refusal && (
                    <div className="addFlowBlocked" role="alert">
                      <p>{refusal.message}</p>
                      {refusal.override_field && (
                        <button type="button" className="btn btnSmall" onClick={() => void upload(true)}>
                          Upload anyway
                        </button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {step === 3 && isWallet && (
            <>
              {walletDone ? (
                <p className="addFlowDone" role="status">
                  ✓ {walletDone}. Its first sync has started; it shows in Accounts &amp; sources.
                </p>
              ) : isMobile ? (
                <p className="card muted cryptoMobileNotice">
                  Connecting a wallet needs a browser extension or a hardware device. Open Data Hub → + Add on a
                  computer to finish this step.
                </p>
              ) : (
                <Suspense fallback={<p role="status">Loading wallet tools…</p>}>
                  <WalletConnectStep chainType={chain ?? "evm"} label={walletLabel} onVerified={setWalletDone} />
                </Suspense>
              )}
            </>
          )}

          {blockedNote}
          {err && (
            <p className="addFlowBlocked" role="alert">
              {err}
            </p>
          )}

          <div className="actions addFlowActions">
            {step > 0 && !locked && (
              <button type="button" className="btn" onClick={() => goTo(step - 1)}>
                Back
              </button>
            )}
            {(step < 2 || (step === 2 && isWallet)) && (
              <button type="button" className="btn btnPrimary" onClick={next}>
                Next
              </button>
            )}
            {step === 2 && !isWallet && (
              <button type="button" className="btn btnPrimary" onClick={() => void createAccount()} disabled={saving}>
                {saving ? "Creating…" : "Create account"}
              </button>
            )}
            {step === 3 && !isWallet && account && !report && (
              <>
                <button type="button" className="btn btnPrimary" onClick={() => void upload()} disabled={uploading}>
                  {uploading ? "Uploading…" : "Upload"}
                </button>
                <Link className="btn" to="/operations/sources">
                  Skip for now
                </Link>
              </>
            )}
            {(report || walletDone) && (
              <>
                <Link className="btn btnPrimary" to="/operations/sources">
                  Done
                </Link>
                <button type="button" className="btn" onClick={restart}>
                  Add another
                </button>
              </>
            )}
            {step < 3 && (
              <Link className="btn addFlowCancel" to="/operations/sources">
                Cancel
              </Link>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
