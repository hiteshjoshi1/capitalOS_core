import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, type SinceLastVisit } from "../lib/api";
import * as fmt from "../lib/format";
import { hasNews, SINCE_VISIT_CHANGE_MIN as CHANGE_MIN } from "../lib/sinceLastVisit";
import { useApiResource } from "../lib/useApiResource";
import "./SinceLastVisitStrip.css";

// #408 (U3, D-112): "Since your last visit" on Overview. On load it reads what changed since
// the stored visit, then records this visit (the server only moves the mark when it's over an
// hour old, so a reload keeps the same comparison). Dismiss moves the mark now.

export default function SinceLastVisitStrip({ baseCurrency }: { baseCurrency: string }) {
  const [data, setData] = useState<SinceLastVisit | null>(null);
  const [dismissed, setDismissed] = useState(false);
  // #475 (V22): "N need action" is the header bell's number, from the same request (one
  // cached Data Hub inbox), so the two can't disagree. The visit reply's own count is only
  // the fallback while the inbox loads or when it fails.
  const inbox = useApiResource("operationsInbox", () => api.operationsInbox(), { staleTimeMs: 60_000 });

  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => api.sinceLastVisit(baseCurrency))
      .then((result) => {
        if (!cancelled) setData(result);
        return api.markVisit(baseCurrency);
      })
      .catch(() => undefined); // the strip is a nicety: no error panel
    return () => {
      cancelled = true;
    };
  }, [baseCurrency]);

  const shown = data ? { ...data, needs_action: inbox.data?.count ?? data.needs_action } : null;
  if (dismissed || !hasNews(shown) || !shown) return null;

  const imports = shown.imports_since ?? 0;
  const actions = shown.needs_action ?? 0;
  const parts: ReactNode[] = [];
  if (shown.change != null && Math.abs(shown.change) >= CHANGE_MIN) {
    parts.push(
      <span key="nw" className={`sinceVisitChange ${shown.change > 0 ? "isUp" : "isDown"}`}>
        {fmt.formatSignedMoney(shown.change, shown.base_currency)} net worth
      </span>,
    );
  }
  if (imports > 0) {
    parts.push(
      <span key="imports">
        {imports} import{imports === 1 ? "" : "s"}
      </span>,
    );
  }
  if (actions > 0) {
    parts.push(
      <Link key="actions" to="/operations">
        {actions} need{actions === 1 ? "s" : ""} action
      </Link>,
    );
  }

  const dismiss = () => {
    setDismissed(true);
    void api.markVisit(baseCurrency, true).catch(() => undefined);
  };

  return (
    <aside className="sinceVisitStrip" aria-label="Since your last visit">
      <p className="sinceVisitText">
        <span className="sinceVisitLead">Since your last visit</span>
        <span className="sinceVisitWhen"> ({fmt.formatDateTime(shown.seen_at)})</span>
        <span className="sinceVisitParts">
          {parts.map((part, i) => (
            <span key={i} className="sinceVisitPart">
              {part}
            </span>
          ))}
        </span>
      </p>
      <button type="button" className="btn btnSmall sinceVisitDismiss" onClick={dismiss}>
        Dismiss
      </button>
    </aside>
  );
}
