// #410 (UX U28): one line on what an upload changed, from the import report's `effect`.
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

function money(amount: number, currency: string, signed = false): string {
  const prefix = currency === "SGD" ? "S$ " : currency === "USD" ? "US$ " : `${currency} `;
  const sign = amount < 0 ? "−" : signed && amount > 0 ? "+" : "";
  return `${sign}${prefix}${Math.abs(amount).toLocaleString("en-SG", { maximumFractionDigits: 0 })}`;
}

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-SG", { day: "numeric", month: "short", timeZone: "UTC" });
}

function monthLabel(month: string): string {
  const d = new Date(`${month}-01T00:00:00Z`);
  return d.toLocaleDateString("en-SG", { month: "short", year: "numeric", timeZone: "UTC" });
}

/** "Balance S$ 12,300 on 31 Oct · net worth for Oct 2026 +S$ 1,250" (no change: "unchanged"). */
export function uploadEffectLine(effect: UploadEffect): string {
  const parts: string[] = [];
  if (effect.balance !== null && effect.balance_date) {
    parts.push(`Balance ${money(effect.balance, effect.base_currency)} on ${dayLabel(effect.balance_date)}`);
  }
  const which = effect.live ? `${monthLabel(effect.month)} so far` : monthLabel(effect.month);
  const change = Math.abs(effect.net_worth_change) < 0.5
    ? "unchanged"
    : `${money(effect.net_worth_change, effect.base_currency, true)} (${money(effect.net_worth_before, effect.base_currency)} → ${money(effect.net_worth_after, effect.base_currency)})`;
  parts.push(`net worth for ${which} ${change}`);
  const line = parts.join(" · ");
  return line.charAt(0).toUpperCase() + line.slice(1);
}
