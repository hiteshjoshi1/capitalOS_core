import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Platform, PlatformOptions } from "../lib/api";
import "../App.css";
import DirectoryListRow from "./DirectoryListRow";
import PlatformDetailsForm, { type PlatformDraft } from "./PlatformDetailsForm";
import SuccessBanner from "./SuccessBanner";
import LoadError from "./LoadError";

type LoadState = "idle" | "loading" | "ready" | "error";

const EMPTY_PLATFORM_FORM: PlatformDraft = {
  code: "",
  name: "",
  platform_type: "",
  country: "",
  website: "",
};

/** The platform directory (banks, brokers, exchanges): add one, list them. Admin settings (#321);
 * it was the Data Hub "Add Platforms" page. */
export default function PlatformDirectory() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [success, setSuccess] = useState<string>("");
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [options, setOptions] = useState<PlatformOptions | null>(null);
  const [platformForm, setPlatformForm] = useState<PlatformDraft>(EMPTY_PLATFORM_FORM);

  async function loadData() {
    const [platformRows, optionRows] = await Promise.all([
      api.platforms(),
      api.platformOptions(),
    ]);
    setPlatforms(platformRows);
    setOptions(optionRows);
  }

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        await loadData();
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, []);

  async function onCreatePlatform(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr("");
    setSuccess("");

    const code = platformForm.code.trim().toUpperCase();
    const name = platformForm.name.trim();
    const platform_type = platformForm.platform_type;
    const country = platformForm.country.trim().toUpperCase();
    const website = platformForm.website.trim();
    if (!code || !name || !platform_type || !country) {
      setErr("Fill all platform fields.");
      return;
    }

    setSaving(true);
    try {
      await api.createPlatform({
        code,
        name,
        platform_type,
        country,
        website: website || null,
      });
      await loadData();
      setPlatformForm(EMPTY_PLATFORM_FORM);
      setSuccess("Platform saved.");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="admin-platforms">
      <h2 className="coSectionTitle" id="admin-platforms">Platform directory</h2>
      <p className="muted">The banks, brokers and exchanges that imports and accounts use.</p>
      {state === "loading" && <div className="card" role="status">Loading…</div>}

      {state === "error" && (
        <LoadError title="Couldn't load platforms" error={err} />
      )}

      {state === "ready" && (
        <div className="wealthOverviewLayout">
          <div className="card">
            <div className="cardTitle">New Platform</div>
            <PlatformDetailsForm
              value={platformForm}
              platformTypes={options?.platform_types ?? []}
              platformCountries={options?.countries ?? []}
              onChange={setPlatformForm}
              onSubmit={onCreatePlatform}
              submitLabel={saving ? "Saving..." : "Save platform"}
            />
            {err ? (
              <div className="hint" role="alert">{err}</div>
            ) : null}
            {success ? <SuccessBanner message={success} onDismiss={() => setSuccess("")} /> : null}
          </div>

          <section aria-label="Registered platforms">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">DIRECTORY</p>
                <h2 className="coSectionTitle">Registered platforms</h2>
              </div>
            </div>
            <div className="card">
              {platforms.length === 0 ? (
                <p className="muted">No platforms configured.</p>
              ) : (
                platforms.map((platform) => (
                  <DirectoryListRow
                    key={platform.id}
                    title={platform.name}
                    meta={`${platform.code} · ${platform.platform_type} · ${platform.country}`}
                    right={<span className="muted">{platform.website ?? "—"}</span>}
                  />
                ))
              )}
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
