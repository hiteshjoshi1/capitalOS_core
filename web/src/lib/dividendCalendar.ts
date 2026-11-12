// #417 (U17, D-117): wording for the dividend calendar.
import type { DividendCalendar } from "./api";

const BASIS_LABEL: Record<string, { label: string; title: string }> = {
  announced: { label: "Date listed", title: "The ex-date is listed by the market-data provider; the amount is estimated from past dividends." },
  projected: { label: "Estimated", title: "Estimated from this holding's past dividends: when it usually pays and how much." },
  your_payments: { label: "From your payments", title: "No market data: what this holding paid you a year ago, a year on." },
};

export function basisLabel(basis: string): { label: string; title: string } {
  return BASIS_LABEL[basis] ?? { label: "Estimated", title: "Estimated" };
}

/** "11 of 58 holdings expected to pay · 36 usually pay at other times of year · 11 with no dividend history". */
export function coverageText(cal: DividendCalendar): string {
  const parts = [
    `${cal.holdings_with_events} of ${cal.holdings_considered} holding${cal.holdings_considered === 1 ? "" : "s"} expected to pay`,
  ];
  const noHistory = cal.holdings_no_dividend_history ?? 0;
  const otherTimes = cal.holdings_without_data - noHistory;
  if (otherTimes > 0) parts.push(`${otherTimes} usually pay at other times of year`);
  if (noHistory > 0) parts.push(`${noHistory} with no dividend history`);
  return parts.join(" · ");
}
