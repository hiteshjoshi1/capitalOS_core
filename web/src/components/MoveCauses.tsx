import type { MoveCauses as MoveCausesData } from "../lib/api";
import { api } from "../lib/api";
import { NO_DATA_CAUSE, causeAmount, shouldShowMoveCauses } from "../lib/moveCauses";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import "./MoveCauses.css";

/**
 * "Why it moved" (#289): the data causes behind a period's change, from the month
 * bridge's `move_causes` (one backend list for Overview and History). Significant causes
 * first; the rest under "Also"; "No data cause found" for a big move without one.
 */
export function MoveCausesList({
  data,
  currency,
  compact = false,
  flagged = false,
}: {
  data: MoveCausesData;
  currency: string;
  compact?: boolean;
  /** History already flagged the month as unusual: say "no data cause" even below 5%. */
  flagged?: boolean;
}) {
  const main = data.causes.filter((c) => c.significant);
  const also = data.causes.filter((c) => !c.significant);
  const noneReason = data.none_reason ?? (flagged && main.length === 0 ? NO_DATA_CAUSE : null);
  return (
    <div className={`moveCauses${compact ? " moveCausesCompact" : ""}`} role="note" aria-label="Why it moved">
      <p className="moveCausesTitle">Why it moved</p>
      {main.length ? (
        <ul className="moveCausesList">
          {main.map((cause) => (
            <li key={`${cause.key}-${cause.account_id ?? ""}-${cause.label}`} className="moveCausesItem" data-testid={`move-cause-${cause.key}`}>
              <span className="moveCausesLabel">{cause.label}</span>
              {causeAmount(cause, currency) ? <span className="moveCausesAmount">{causeAmount(cause, currency)}</span> : null}
              {cause.detail && !compact ? <span className="moveCausesDetail muted">{cause.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {noneReason ? <p className="moveCausesNone muted">{noneReason}</p> : null}
      {also.length ? (
        <p className="moveCausesAlso muted">
          Also: {also.map((c) => [c.label, causeAmount(c, currency)].filter(Boolean).join(" · ")).join("; ")}
        </p>
      ) : null}
    </div>
  );
}

/** Overview's "Why it moved" under the headline deltas: shares the bridge card's fetch. */
export default function MoveCauses({ month, baseCurrency }: { month: string; baseCurrency: string }) {
  const res = useApiResource(resourceKey("monthBridge", month, baseCurrency), () => api.monthBridge(month, baseCurrency));
  const data = res.data?.move_causes ?? null;
  if (!data || !shouldShowMoveCauses(data)) return null;
  return <MoveCausesList data={data} currency={res.data?.base_currency || baseCurrency} />;
}

/** History's drill-down (#289): the causes for a month History flagged as unusual or
 * catch-up, from that month's bridge (fetched only when flagged). */
export function MonthMoveCauses({ month, baseCurrency }: { month: string; baseCurrency: string }) {
  const res = useApiResource(resourceKey("monthBridge", month, baseCurrency), () => api.monthBridge(month, baseCurrency));
  const data = res.data?.move_causes ?? null;
  if (!data) return null;
  return <MoveCausesList data={data} currency={res.data?.base_currency || baseCurrency} compact flagged />;
}
