import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import type { BridgeLine, BridgeMover, BridgeTrade, MonthBridge } from "../lib/api";
import * as fmt from "../lib/format";
import { noDataFor } from "../lib/delta";
import { BRIDGE_LINKS } from "../lib/monthBridge";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import Delta from "./Delta";
import FxNote from "./FxNote";
import LoadError from "./LoadError";
import "./MonthBridgeCard.css";

const CAUSE_LABEL: Record<string, string> = {
  price: "price",
  quantity: "quantity",
  fx: "FX",
  unknown: "statement value",
};

/** "stocks +S$ 15,100 · crypto +S$ 4,300": the line's non-zero parts (#254: compact is for chart labels only). */
function partsSummary(line: BridgeLine, currency: string): string | null {
  const shown = line.parts.filter((part) => Math.abs(part.amount) >= 0.5);
  if (shown.length < 2) return null;
  return shown
    .map((part) => `${part.label.toLowerCase()} ${fmt.formatSignedMoney(part.amount, currency)}`)
    .join(" · ");
}

function BridgeRow({
  line,
  currency,
  muted = false,
}: {
  line: BridgeLine;
  currency: string;
  muted?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const link = BRIDGE_LINKS[line.key];
  const summary = partsSummary(line, currency);
  const hasDetail = line.parts.length > 0 || line.notes.length > 0 || Boolean(line.reason);
  return (
    <li className={`monthBridgeRow${muted ? " monthBridgeRowMuted" : ""}`} data-testid={`bridge-line-${line.key}`}>
      <div className="monthBridgeRowMain">
        <span className="monthBridgeLabel">
          {hasDetail ? (
            <button
              type="button"
              className="monthBridgeToggle"
              aria-expanded={open}
              aria-controls={detailId}
              onClick={() => setOpen((value) => !value)}
            >
              <span aria-hidden="true">{open ? "▾" : "▸"}</span> {line.label}
            </button>
          ) : (
            line.label
          )}
          {line.status !== "ok" ? (
            <span className="monthBridgeStatus" title={line.reason ?? undefined}>
              {line.status === "unavailable" ? "not available" : "partial"}
            </span>
          ) : null}
        </span>
        <span className="monthBridgeAmount">
          <Delta abs={line.amount} currency={currency} show="abs" />
        </span>
      </div>
      {summary && !open ? <p className="monthBridgeSummary muted">{summary}</p> : null}
      {open ? (
        <div className="monthBridgeDetail" id={detailId}>
          {line.reason ? (
            <p className={line.status === "ok" ? "monthBridgeNote muted" : "monthBridgeReason"}>{line.reason}</p>
          ) : null}
          {line.parts.length > 0 ? (
            <ul className="monthBridgeParts">
              {line.parts.map((part) => (
                <li key={part.key}>
                  <div className="monthBridgePartRow">
                    <span>{part.label}</span>
                    <span>{fmt.formatSignedMoney(part.amount, currency)}</span>
                  </div>
                  {/* #332: what the part is made of, so "which one?" is answered here. */}
                  {(part.items ?? []).length > 0 ? (
                    <ul className="monthBridgeItems" aria-label={`${part.label}: items`}>
                      {(part.items ?? []).map((item, index) => (
                        <li key={`${item.label}-${index}`}>
                          <div className="monthBridgePartRow">
                            <span>
                              {item.link ? <Link to={item.link}>{item.label}</Link> : item.label}
                            </span>
                            <span>{item.amount == null ? "—" : fmt.formatSignedMoney(item.amount, currency)}</span>
                          </div>
                          {item.reason ? <p className="monthBridgeItemReason muted">{item.reason}</p> : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {line.notes.map((note) => (
            <p key={note.key} className="monthBridgeNote muted">
              {note.label}
              {note.amount != null ? `: ${fmt.formatMoney(note.amount, currency)}` : ""}
            </p>
          ))}
          {link ? (
            <Link className="wealthInlineLink" to={link.to}>
              {link.label}
            </Link>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function MoverChip({ mover, currency }: { mover: BridgeMover; currency: string }) {
  // What the market did (price + FX); buying or selling is listed under trades.
  const amount = mover.market_effect ?? mover.change;
  return (
    <li className="monthBridgeMover" data-testid={`bridge-mover-${mover.symbol}`}>
      <strong>{mover.symbol}</strong> <Delta abs={amount} currency={currency} show="abs" />{" "}
      <span className="muted">({CAUSE_LABEL[mover.cause] ?? mover.cause})</span>
    </li>
  );
}

const TRADE_LABEL: Record<string, string> = {
  bought: "Bought",
  sold: "Sold",
  moved_in: "Moved in",
  moved_out: "Moved out",
};

function TradeChip({ trade, currency }: { trade: BridgeTrade; currency: string }) {
  const note = trade.side === "sold" && trade.cash_recorded
    ? "to cash"
    : trade.side === "bought" && trade.cash_recorded
      ? "from cash"
      : null;
  return (
    <li className="monthBridgeMover" data-testid={`bridge-trade-${trade.symbol}`}>
      {TRADE_LABEL[trade.side] ?? trade.side} <strong>{trade.symbol}</strong>{" "}
      {fmt.formatMoney(Math.abs(trade.amount), currency)}
      {note ? <span className="muted"> ({note})</span> : null}
    </li>
  );
}

/**
 * Overview's "This month" bridge (#240, D-60, mock-up A in #131): the last month-end
 * close, what moved it, and the figure the hero shows, for the selected month (live
 * month to date, or a past month's month-end). The lines always add up: what can't be
 * computed says why and is in "Unexplained", which is shown, not hidden.
 */
export default function MonthBridgeCard({ month, baseCurrency }: { month: string; baseCurrency: string }) {
  const headingId = useId();
  const res = useApiResource(resourceKey("monthBridge", month, baseCurrency), () =>
    api.monthBridge(month, baseCurrency),
  );
  const bridge: MonthBridge | null = res.data ?? null;
  const currency = bridge?.base_currency || baseCurrency;
  const startLabel = bridge ? `${fmt.formatMonth(bridge.start.month, "medium")} close` : "";
  const endLabel = bridge
    ? bridge.is_live
      ? `Now · ${fmt.formatDate(bridge.end.boundary_at)}`
      : `${fmt.formatMonth(bridge.end.month, "medium")} close`
    : "";

  return (
    <section className="monthBridgeCard" aria-labelledby={headingId} data-testid="month-bridge">
      <div className="coSectionHeaderSimple">
        <p className="coEyebrow" id={headingId}>
          {bridge && !bridge.is_live ? `${fmt.formatMonth(bridge.end.month, "medium").toUpperCase()}` : "THIS MONTH"}
        </p>
        <h2 className="coSectionTitle">
          {bridge ? `What moved net worth since the ${startLabel}` : "What moved net worth"}
        </h2>
      </div>

      {res.isLoading ? (
        <p className="muted" role="status">
          Loading this month…
        </p>
      ) : res.error && !bridge ? (
        <LoadError compact title="Couldn't load this month's changes" error={res.error} onRetry={() => void res.reload().catch(() => undefined)} />
      ) : bridge && bridge.start.baseline_missing ? (
        <p className="muted" data-testid="bridge-no-baseline">
          No comparison: {noDataFor(bridge.start.month)}.
        </p>
      ) : bridge ? (
        <>
          <ol className="monthBridgeList">
            <li className="monthBridgeRow monthBridgeEnd" data-testid="bridge-start">
              <div className="monthBridgeRowMain">
                <span className="monthBridgeLabel">{startLabel}</span>
                <span className="monthBridgeAmount">{fmt.formatMoney(bridge.start.value, currency)}</span>
              </div>
            </li>
            {bridge.lines.map((line) => (
              <BridgeRow key={line.key} line={line} currency={currency} />
            ))}
            <BridgeRow line={bridge.unexplained} currency={currency} muted />
            <li className="monthBridgeRow monthBridgeEnd" data-testid="bridge-end">
              <div className="monthBridgeRowMain">
                <span className="monthBridgeLabel">= {endLabel}</span>
                <span className="monthBridgeAmount">{fmt.formatMoney(bridge.end.value, currency)}</span>
              </div>
            </li>
          </ol>
          <p className="monthBridgeFoot muted">
            {bridge.is_live ? "Month to date" : "Whole month"}: flows from {fmt.formatDate(bridge.period_start)}.
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
