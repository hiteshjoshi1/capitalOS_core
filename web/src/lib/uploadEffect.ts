// #410 (UX U28): one line on what an upload changed, from the import report's `effect`.
import { formatDayMonth, formatMoney, formatMonth, formatSignedMoney } from "./format";

export type UploadEffect = {
  month: string; // YYYY-MM
  live: boolean;
  base_currency: string;
  balance: number | null;
  balance_date: string | null; // YYYY-MM-DD
  net_worth_before: number;
  net_worth_after: number;
  net_worth_change: number;
};

/** "Balance S$ 12,300 on 31 Oct · net worth for Oct 2026 +S$ 1,250" (no change: "unchanged"). */
export function uploadEffectLine(effect: UploadEffect): string {
  const parts: string[] = [];
  if (effect.balance !== null && effect.balance_date) {
    parts.push(`Balance ${formatMoney(effect.balance, effect.base_currency, { decimals: 0 })} on ${formatDayMonth(effect.balance_date)}`);
  }
  const month = formatMonth(effect.month, "medium");
  const which = effect.live ? `${month} so far` : month;
  const change = Math.abs(effect.net_worth_change) < 0.5
    ? "unchanged"
    : `${formatSignedMoney(effect.net_worth_change, effect.base_currency, { decimals: 0 })} (${formatMoney(effect.net_worth_before, effect.base_currency, { decimals: 0 })} → ${formatMoney(effect.net_worth_after, effect.base_currency, { decimals: 0 })})`;
  parts.push(`net worth for ${which} ${change}`);
  const line = parts.join(" · ");
  return line.charAt(0).toUpperCase() + line.slice(1);
}
