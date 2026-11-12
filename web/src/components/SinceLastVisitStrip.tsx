import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, type SinceLastVisit } from "../lib/api";
import * as fmt from "../lib/format";
import { hasNews, SINCE_VISIT_CHANGE_MIN as CHANGE_MIN } from "../lib/sinceLastVisit";
import "./SinceLastVisitStrip.css";

// #408 (U3, D-112): "Since your last visit" on Overview. On load it reads what changed since
// the stored visit, then records this visit (the server only moves the mark when it's over an
// hour old, so a reload keeps the same comparison). Dismiss moves the mark now.

export default function SinceLastVisitStrip({ baseCurrency }: { baseCurrency: string }) {
  const [data, setData] = useState<SinceLastVisit | null>(null);
  const [dismissed, setDismissed] = useState(false);

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

  if (dismissed || !hasNews(data) || !data) return null;

  const imports = data.imports_since ?? 0;
  const actions = data.needs_action ?? 0;
  const parts: ReactNode[] = [];
  if (data.change != null && Math.abs(data.change) >= CHANGE_MIN) {
    parts.push(
      <span key="nw" className={`sinceVisitChange ${data.change > 0 ? "isUp" : "isDown"}`}>
        {fmt.formatSignedMoney(data.change, data.base_currency)} net worth
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
        <span className="sinceVisitWhen"> ({fmt.formatDateTime(data.seen_at)})</span>
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
