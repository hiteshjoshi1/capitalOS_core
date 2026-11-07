import { createContext, useCallback, useContext, useEffect, useId, useMemo, useState, type ReactNode } from "react";

import { fxNoteText } from "../lib/fxNote";
import { api, type FxBackfillResult, type FxStatus } from "../lib/api";
import { useAuth } from "../context/useAuth";
import { useBaseCurrency } from "../context/CurrencyContext";
import * as fmt from "../lib/format";

type Registry = { register: (id: string, sources: FxStatus[]) => void; unregister: (id: string) => void };

const FxNoteRegistry = createContext<Registry | null>(null);
const FxNoteSources = createContext<FxStatus[]>([]);

function normalize(sources: Array<FxStatus | null | undefined>): FxStatus[] {
  return sources
    .filter((s): s is FxStatus => s != null)
    .map((s) => ({
      fx_missing_currencies: [...(s.fx_missing_currencies ?? [])].sort(),
      fx_stale_currencies: [...(s.fx_stale_currencies ?? [])].sort(),
    }))
    .filter((s) => s.fx_missing_currencies.length > 0 || s.fx_stale_currencies.length > 0);
}

/**
 * One FX note per page (#290): every `<FxNote>` inside the scope reports its sources
 * here instead of rendering its own copy, and `<PageFxNote>` shows them once.
 * PageShell provides the scope; outside it an `<FxNote>` renders inline (#139).
 */
export function FxNoteScope({ children }: { children: ReactNode }) {
  const [byId, setById] = useState<Record<string, FxStatus[]>>({});
  const register = useCallback((id: string, sources: FxStatus[]) => {
    setById((prev) => ({ ...prev, [id]: sources }));
  }, []);
  const unregister = useCallback((id: string) => {
    setById((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);
  const registry = useMemo(() => ({ register, unregister }), [register, unregister]);
  const all = useMemo(() => Object.values(byId).flat(), [byId]);
  return (
    <FxNoteRegistry.Provider value={registry}>
      <FxNoteSources.Provider value={all}>{children}</FxNoteSources.Provider>
    </FxNoteRegistry.Provider>
  );
}

/** A small, muted note under a total; renders nothing when FX is complete. In a
 *  page scope it hands its sources to the page's single note instead (#290). */
export default function FxNote({ sources }: { sources: Array<FxStatus | null | undefined> }) {
  const registry = useContext(FxNoteRegistry);
  const id = useId();
  const normalized = normalize(sources);
  const key = JSON.stringify(normalized);

  useEffect(() => {
    if (!registry) return undefined;
    registry.register(id, JSON.parse(key) as FxStatus[]);
    return () => registry.unregister(id);
  }, [registry, id, key]);

  if (registry) return null;
  const text = fxNoteText(...sources);
  if (!text) return null;
  return (
    <p className="coHeroFreshness" role="note" data-testid="fx-note">
      {text}
    </p>
  );
}

function backfillSummary(result: FxBackfillResult): string {
  if (result.status === "up_to_date") return "Every past rate for your data is already stored.";
  if (result.status === "remote_disabled") return "Fetching rates is turned off on this install (FX_DISABLE_REMOTE).";
  if (result.status === "failed") return "The rate provider didn't answer. Try again later.";
  const span =
    result.span_start && result.span_end
      ? ` for ${fmt.formatDate(result.span_start)} to ${fmt.formatDate(result.span_end)}`
      : "";
  const more = result.remaining_requests > 0 ? " More remain: fetch again to continue." : "";
  const unsupported =
    result.unsupported_currencies.length > 0
      ? ` The provider has no rates for ${result.unsupported_currencies.join(", ")}.`
      : "";
  return `Fetched past exchange rates${span}. Reload to see them.${more}${unsupported}`;
}

/** The page's one FX note (#290), with a way to fetch the missing past rates
 *  (admins: shared data, #152). Nothing when every value converted. */
export function PageFxNote() {
  const sources = useContext(FxNoteSources);
  const { user } = useAuth();
  const [baseCurrency] = useBaseCurrency();
  const [state, setState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [message, setMessage] = useState<string>("");
  const text = fxNoteText(...sources);
  if (!text) return null;

  const fetchRates = async () => {
    setState("running");
    try {
      const result = await api.fxBackfill(baseCurrency);
      setMessage(backfillSummary(result));
      setState("done");
    } catch {
      setMessage("Couldn't fetch the missing rates. Try again later.");
      setState("error");
    }
  };

  return (
    <div className="fxPageNote" role="note" data-testid="fx-note">
      <p className="coHeroFreshness">{text}</p>
      {user?.is_admin ? (
        <div className="fxPageNoteActions">
          <button type="button" className="btn" disabled={state === "running"} onClick={() => void fetchRates()}>
            {state === "running" ? "Fetching rates…" : "Fetch missing rates"}
          </button>
          {state === "done" || state === "error" ? (
            <span className="fxPageNoteResult" role="status">
              {message}
              {state === "done" ? (
                <>
                  {" "}
                  <button type="button" className="linkButton" onClick={() => window.location.reload()}>
                    Reload
                  </button>
                </>
              ) : null}
            </span>
          ) : null}
        </div>
      ) : (
        <p className="coHeroFreshness">An admin can fetch the missing rates.</p>
      )}
    </div>
  );
}
