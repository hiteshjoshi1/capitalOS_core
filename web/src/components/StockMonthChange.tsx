import { useId, useState, type ReactNode } from "react";

import type { StockMonthChange as Change } from "../lib/api";
import { noDataFor } from "../lib/delta";
import * as fmt from "../lib/format";
import Delta from "./Delta";
import "./StockMonthChange.css";

// #251 (#131 mock-up C): a holding's change vs the compare month-end on the Stocks page,
// split into price, quantity and FX by Overview's bridge split (D-60), in the base
// currency, with the local-currency detail behind a tap (and on hover). Buying or
// selling is a change in quantity, not a gain or a loss: a sold holding reads "Sold",
// and a change that includes a trade isn't coloured as one.

/** A change in quantity this big (base currency) is a trade, as the bridge lists it. */
const TRADE_MIN = 1;
/** An unsplit part this big is shown. */
const UNSPLIT_MIN = 0.5;

type Props = {
  change: Change | null | undefined;
  /** The base currency the amounts are in. */
  currency: string;
  /** The compare month-end, e.g. "28 Feb 2026". */
  compareLabel: string;
  symbol: string;
  /** `cell`: the table's column (breakdown on hover/tap); `card`: the mobile card (breakdown shown). */
  layout?: "cell" | "card";
};

function sharesText(change: Change): string | null {
  const before = change.start_quantity ?? 0;
  const after = change.end_quantity ?? 0;
  const moved = after - before;
  if (change.side === "sold") return `sold ${fmt.formatNumber(before, 4)} shares`;
  if (change.side === "new") return `bought ${fmt.formatNumber(after, 4)} shares`;
  if (change.start_quantity == null || change.end_quantity == null) return null;
  if (Math.abs(moved) < 1e-9) return "no shares added or sold";
  return moved > 0 ? `bought ${fmt.formatNumber(moved, 4)} shares` : `sold ${fmt.formatNumber(-moved, 4)} shares`;
}

function priceText(change: Change): string | null {
  const currency = change.price_currency;
  if (!currency || change.start_price == null || change.end_price == null) return null;
  const local = change.start_quantity != null ? change.start_quantity * (change.end_price - change.start_price) : null;
  const move = `${fmt.formatMoney(change.start_price, currency, { decimals: 2 })} → ${fmt.formatMoney(change.end_price, currency, { decimals: 2 })}`;
  return local != null ? `${move} (${fmt.formatSignedMoney(local, currency, { decimals: 2 })})` : move;
}

function fxText(change: Change, currency: string): string | null {
  const local = change.price_currency;
  if (!local || change.start_rate == null || change.end_rate == null || change.start_rate <= 0) return null;
  if (local.toUpperCase() === currency.toUpperCase()) return `in ${local}: no FX`;
  return `${local} ${fmt.formatPercent(change.end_rate / change.start_rate - 1, { signed: true, decimals: 2 })} vs ${currency.toUpperCase()}`;
}

type Part = { key: string; label: string; amount: number; detail: string | null };

function parts(change: Change, currency: string): Part[] {
  const out: Part[] = [];
  if (change.side !== "sold" && change.side !== "new") {
    out.push({ key: "price", label: "Price", amount: change.price_effect, detail: priceText(change) });
  }
  out.push({ key: "quantity", label: "Quantity", amount: change.quantity_effect, detail: sharesText(change) });
  if (change.side !== "sold" && change.side !== "new") {
    out.push({ key: "fx", label: "FX", amount: change.fx_effect, detail: fxText(change, currency) });
  }
  if (Math.abs(change.unsplit) >= UNSPLIT_MIN) {
    out.push({
      key: "unsplit",
      label: "Not split",
      amount: change.unsplit,
      detail: "no price or quantity on one side, or a statement value that isn't quantity × price",
    });
  }
  return out;
}

/** One line for the hover title: "Price +S$ 402 (190.00 → 205.00 USD) · Quantity …". */
function summaryText(change: Change, currency: string, compareLabel: string): string {
  const lines = parts(change, currency).map(
    (part) => `${part.label} ${fmt.formatSignedMoney(part.amount, currency)}${part.detail ? ` (${part.detail})` : ""}`,
  );
  lines.push(`was ${fmt.formatMoney(change.compare_value, currency)} at ${compareLabel} close`);
  return lines.join(" · ");
}

export default function StockMonthChange({ change, currency, compareLabel, symbol, layout = "cell" }: Props) {
  const [open, setOpen] = useState(false);
  const noteId = useId();
  if (!change) return <span className="stockMonthChange stockMonthChange--missing">{fmt.MISSING}</span>;
  if (change.baseline_missing) {
    return (
      <span className="stockMonthChange stockMonthChange--missing" title={`no comparison: ${noDataFor(change.compare_month)}`}>
        {fmt.MISSING}
      </span>
    );
  }

  const traded = Math.abs(change.quantity_effect) >= TRADE_MIN;
  const breakdown = parts(change, currency);
  const title = summaryText(change, currency, compareLabel);

  let headline: ReactNode;
  if (change.side === "sold") {
    // A sale, never a loss: no arrow, no colour, and what it was worth.
    headline = (
      <span className="stockMonthChangeHeadline">
        <span className="stockMonthChangeTag stockMonthChangeTag--sold">Sold</span>
        <span className="stockMonthChangeNeutral">was {fmt.formatMoney(change.compare_value, currency)}</span>
      </span>
    );
  } else if (change.side === "new") {
    headline = (
      <span className="stockMonthChangeHeadline">
        <span className="stockMonthChangeTag">New</span>
        <span className="stockMonthChangeNeutral">{fmt.formatSignedMoney(change.abs, currency)}</span>
      </span>
    );
  } else if (traded) {
    // Part of the change is a purchase or a sale: shown, but not coloured as a gain or loss.
    const market = change.price_effect + change.fx_effect;
    headline = (
      <span className="stockMonthChangeHeadline">
        <span className="stockMonthChangeNeutral">{fmt.formatSignedMoney(change.abs, currency)}</span>
        <small className="stockMonthChangeSub">
          {change.quantity_effect > 0 ? "bought" : "sold"} {fmt.formatMoney(Math.abs(change.quantity_effect), currency)}
          {" · market "}
          {fmt.formatSignedMoney(market, currency)}
        </small>
      </span>
    );
  } else {
    headline = (
      <span className="stockMonthChangeHeadline">
        <Delta abs={change.abs} compareValue={change.compare_value} currency={currency} />
      </span>
    );
  }

  return (
    <span className={`stockMonthChange stockMonthChange--${layout}`} data-side={change.side}>
      <button
        type="button"
        className="stockMonthChangeToggle"
        title={title}
        aria-expanded={open}
        aria-controls={noteId}
        aria-label={`${symbol} since ${compareLabel}: ${fmt.formatSignedMoney(change.abs, currency)}${change.side === "sold" ? ", sold" : ""}. Show price, quantity and FX`}
        onClick={() => setOpen((value) => !value)}
      >
        {headline}
      </button>
      {layout === "card" ? (
        <span className="stockMonthChangeParts" aria-hidden="true">
          {breakdown.map((part) => (
            <span key={part.key}>
              {part.label} {fmt.formatSignedMoney(part.amount, currency)}
            </span>
          ))}
        </span>
      ) : null}
      {open ? (
        <span id={noteId} className="stockMonthChangeNote" role="note">
          {breakdown.map((part) => (
            <span className="stockMonthChangeNoteRow" key={part.key}>
              <span className="stockMonthChangeNoteLabel">{part.label}</span>
              <span className="stockMonthChangeNoteAmount">{fmt.formatSignedMoney(part.amount, currency)}</span>
              {part.detail ? <span className="stockMonthChangeNoteDetail">{part.detail}</span> : null}
            </span>
          ))}
          <span className="stockMonthChangeNoteFoot">
            vs {fmt.formatMoney(change.compare_value, currency)} at {compareLabel} close
          </span>
        </span>
      ) : null}
    </span>
  );
}
