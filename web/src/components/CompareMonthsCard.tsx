import { useId, useMemo } from "react";

import { api } from "../lib/api";
import type { SpanBridge } from "../lib/api";
import * as fmt from "../lib/format";
import { noDataFor } from "../lib/delta";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import FxNote from "./FxNote";
import LoadError from "./LoadError";
import { BridgeRow, MoverChip, TradeChip } from "./MonthBridgeCard";
import "./MonthBridgeCard.css";
import "./CompareMonthsCard.css";

type Props = {
  from: string;
  to: string;
  /** Months the pickers offer, newest first. */
  months: string[];
  baseCurrency: string;
  onChange: (next: { from: string; to: string }) => void;
};

/**
 * History → Compare (#398, U20, D-110): pick two months and see what moved net worth from
 * the first one's close to the second's, line by line: the month bridges in between added
 * up. Like Overview's "This month", the lines always add up to the end; what can't be
 * computed is in Unexplained.
 */
export default function CompareMonthsCard({ from, to, months, baseCurrency, onChange }: Props) {
  const headingId = useId();
  const fromId = useId();
  const toId = useId();
  const valid = from <= to;
  const res = useApiResource(valid ? resourceKey("spanBridge", from, to, baseCurrency) : null, () =>
    api.spanBridge(from, to, baseCurrency),
  );
  const bridge: SpanBridge | null = valid ? (res.data ?? null) : null;
  const currency = bridge?.base_currency || baseCurrency;
  const endLabel = bridge
    ? bridge.is_live
      ? `Now · ${fmt.formatDate(bridge.end.boundary_at)}`
      : `${fmt.formatMonth(bridge.end.month, "medium")} close`
    : "";
  const startLabel = bridge ? `${fmt.formatMonth(bridge.start.month, "medium")} close` : "";
  const biggestMonth = useMemo(() => {
    if (!bridge || bridge.months.length < 2) return null;
    return bridge.months.reduce((best, m) => (Math.abs(m.change) > Math.abs(best.change) ? m : best));
  }, [bridge]);

  return (
    <section className="monthBridgeCard compareMonthsCard" aria-labelledby={headingId} data-testid="compare-months">
      <div className="coSectionHeaderSimple">
        <p className="coEyebrow" id={headingId}>
          COMPARE TWO MONTHS
        </p>
        <h2 className="coSectionTitle">What moved net worth between two month-ends</h2>
      </div>

      <div className="compareMonthsPickers">
        <label htmlFor={fromId}>
          From the close of
          <select id={fromId} value={from} onChange={(e) => onChange({ from: e.target.value, to })}>
            {months.map((m) => (
              <option key={m} value={m}>
                {fmt.formatMonth(m, "medium")}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor={toId}>
          to
          <select id={toId} value={to} onChange={(e) => onChange({ from, to: e.target.value })}>
            {months.map((m) => (
              <option key={m} value={m}>
                {m === fmt.currentMonth() ? `${fmt.formatMonth(m, "medium")} (now)` : fmt.formatMonth(m, "medium")}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!valid ? (
        <p className="muted" role="alert" data-testid="compare-invalid">
          Pick a "from" month before the "to" month.
        </p>
      ) : res.isLoading ? (
        <p className="muted" role="status">
          Adding up the months in between…
        </p>
      ) : res.error && !bridge ? (
        <LoadError compact title="Couldn't compare these months" error={res.error} onRetry={() => void res.reload().catch(() => undefined)} />
      ) : bridge && bridge.months.length === 0 ? (
        <p className="muted" data-testid="compare-same-month">
          Same month on both sides: nothing changed.
        </p>
      ) : bridge && bridge.start.baseline_missing ? (
        <p className="muted" data-testid="compare-no-baseline">
          No comparison: {noDataFor(bridge.start.month)}. Pick a later "from" month.
        </p>
      ) : bridge ? (
        <>
          <p className="compareMonthsSummary" data-testid="compare-summary">
            {fmt.formatSignedMoney(bridge.change, currency)} over {bridge.months.length} month
            {bridge.months.length === 1 ? "" : "s"}
            {biggestMonth ? (
              <span className="muted">
                {" "}
                · biggest move {fmt.formatMonth(biggestMonth.month, "medium")} ({fmt.formatSignedMoney(biggestMonth.change, currency)})
              </span>
            ) : null}
          </p>
          <ol className="monthBridgeList">
            <li className="monthBridgeRow monthBridgeEnd" data-testid="compare-start">
              <div className="monthBridgeRowMain">
                <span className="monthBridgeLabel">{startLabel}</span>
                <span className="monthBridgeAmount">{fmt.formatMoney(bridge.start.value, currency)}</span>
              </div>
            </li>
            {bridge.lines.map((line) => (
              <BridgeRow key={line.key} line={line} currency={currency} />
            ))}
            <BridgeRow line={bridge.unexplained} currency={currency} muted />
            <li className="monthBridgeRow monthBridgeEnd" data-testid="compare-end">
              <div className="monthBridgeRowMain">
                <span className="monthBridgeLabel">= {endLabel}</span>
                <span className="monthBridgeAmount">{fmt.formatMoney(bridge.end.value, currency)}</span>
              </div>
            </li>
          </ol>
          <p className="monthBridgeFoot muted">
            Each month is worked out as on Overview, then added up.
            {Math.abs(bridge.liabilities_change) >= 0.5
              ? ` Cards owe ${fmt.formatMoney(Math.abs(bridge.liabilities_change), currency)} ${
                  bridge.liabilities_change > 0 ? "more" : "less"
                } than at the start; card spending is in Cash kept.`
              : ""}
          </p>
          {bridge.movers.length > 0 ? (
            <div className="monthBridgeMovers">
              <span className="coSignalEyebrow">TOP MOVERS</span>
              <ul>
                {bridge.movers.map((mover) => (
                  <MoverChip key={`${mover.asset_class}-${mover.symbol}`} mover={mover} currency={currency} />
                ))}
              </ul>
            </div>
          ) : null}
          {(bridge.trades ?? []).length > 0 ? (
            <div className="monthBridgeMovers">
              <span className="coSignalEyebrow">BOUGHT AND SOLD</span>
              <ul>
                {(bridge.trades ?? []).map((trade) => (
                  <TradeChip key={`${trade.asset_class}-${trade.symbol}`} trade={trade} currency={currency} />
                ))}
              </ul>
            </div>
          ) : null}
          <FxNote sources={[bridge]} />
        </>
      ) : null}
    </section>
  );
}
