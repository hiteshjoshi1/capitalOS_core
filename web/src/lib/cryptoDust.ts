import * as fmt from "./format";

/** The dust rule's size in USD (#475, V12: shown and applied in the base currency). */
export const DUST_USD = 10;

export type DustRule = {
  /** The currency the threshold is in and named in ("under S$ 10"). */
  currency: string;
  amount: number;
  /** Which holding value it is compared with. */
  field: "value_base" | "value_usd";
};

/** 13.3 → 10, 78 → 80, 837 → 800: one significant figure, so the label reads as a round number. */
function roundNice(value: number): number {
  const step = 10 ** Math.floor(Math.log10(value));
  return Math.max(step, Math.round(value / step) * step);
}

/**
 * #475 (V12): "Show holdings under S$ 10" on a page shown in S$. USD 10 is converted to the
 * base currency at the page's own rate (its base total over its USD total) and rounded to a
 * round number, then compared with each holding's base value. Without a usable rate (no
 * holdings, or no exchange rate: base total 0), the rule stays USD 10 on the USD value.
 */
export function dustRule(
  summary: { base_currency?: string | null; total_crypto_usd?: number | null; total_crypto_base?: number | null } | null | undefined,
): DustRule {
  const usdRule: DustRule = { currency: "USD", amount: DUST_USD, field: "value_usd" };
  const base = (summary?.base_currency ?? "").toUpperCase();
  const usd = summary?.total_crypto_usd ?? 0;
  const baseTotal = summary?.total_crypto_base ?? 0;
  if (!base || base === "USD" || !(usd > 0) || !(baseTotal > 0)) return usdRule;
  return { currency: base, amount: roundNice((DUST_USD * baseTotal) / usd), field: "value_base" };
}

export function isDust(holding: { value_base: number; value_usd: number }, rule: DustRule): boolean {
  return holding[rule.field] < rule.amount;
}

/** "S$ 10", "INR 800", "USD 10". */
export function dustLabel(rule: DustRule): string {
  return fmt.formatMoney(rule.amount, rule.currency, { decimals: 0 });
}
