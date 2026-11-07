import * as fmt from "../lib/format";
import { deltaDirection, deltaPercent } from "../lib/delta";

export type DeltaProps = {
  /** The change, in `currency`. */
  abs: number | null | undefined;
  /** The change as a fraction (0.031 = 3.1%), already computed in `currency`. Ignored when `compareValue` is given. */
  pct?: number | null;
  /** The baseline amount in `currency`: the % is computed from it, so amount and % can't disagree. */
  compareValue?: number | null;
  /** What the change is measured against, shown after it: "vs Oct 2026". */
  baseline?: string | null;
  currency: string | null | undefined;
  /** Set when there is no baseline: renders "no comparison: <reason>" instead of a number. */
  missingReason?: string | null;
  /** What to print (default both: `+S$ 1,234 (+3.1%)`). `pct` falls back to the amount when there is no %. */
  show?: "both" | "abs" | "pct";
  variant?: "inline" | "chip";
  /** `inverse` when up is bad (spending): the arrow follows the direction, the colour follows good/bad. */
  tone?: "normal" | "inverse";
  decimals?: number;
  className?: string;
};

/**
 * The ▲/▼ alone (#268), for a figure already formatted elsewhere but coloured good/bad, so colour
 * is never the only signal. Nothing for flat. Hidden from screen readers: the sign carries it.
 */
export function DeltaArrow({ direction }: { direction: "up" | "down" | "flat" }) {
  if (direction === "flat") return null;
  return (
    <span className="deltaArrow" aria-hidden="true">
      {direction === "up" ? "▲ " : "▼ "}
    </span>
  );
}

/**
 * The one way a change is shown (#224): ▲/▼ plus one colour pair (`--delta-up` /
 * `--delta-down`), the % in the same currency as the amount, and a sentence instead
 * of a number when the baseline is missing.
 */
export default function Delta({
  abs,
  pct,
  compareValue,
  baseline,
  currency,
  missingReason,
  show = "both",
  variant = "inline",
  tone = "normal",
  decimals,
  className,
}: DeltaProps) {
  const classes = ["delta", variant === "chip" ? "deltaChip" : "", className ?? ""];

  if (missingReason) {
    return (
      <span className={[...classes, "delta--missing"].filter(Boolean).join(" ")} data-direction="missing">
        no comparison: {missingReason}
      </span>
    );
  }
  if (typeof abs !== "number" || !Number.isFinite(abs)) {
    return (
      <span className={[...classes, "delta--missing"].filter(Boolean).join(" ")} data-direction="missing">
        {fmt.MISSING}
      </span>
    );
  }

  const direction = deltaDirection(abs);
  const percent = compareValue !== undefined ? deltaPercent(abs, compareValue) : (pct ?? null);
  const money = fmt.formatSignedMoney(abs, currency, { decimals });
  const pctText = percent == null ? null : fmt.formatPercent(percent, { signed: true });
  const text =
    show === "abs" ? money : show === "pct" ? (pctText ?? money) : pctText ? `${money} (${pctText})` : money;
  // The colour class: "up" is the good colour. Inverse tone (spending) flips it.
  const colour =
    direction === "flat" ? "delta--flat" : (direction === "up") === (tone === "normal") ? "delta--up" : "delta--down";

  return (
    <span className={[...classes, colour].filter(Boolean).join(" ")} data-direction={direction}>
      {direction !== "flat" ? (
        <span className="deltaArrow" aria-hidden="true">
          {direction === "up" ? "▲" : "▼"}
        </span>
      ) : null}
      <span className="deltaValue">{text}</span>
      {baseline ? <span className="deltaBaseline">{baseline}</span> : null}
    </span>
  );
}
