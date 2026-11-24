import * as fmt from "./format";

/** #475 (V11): the one line a month with no sales this year shows: "No sales in 2026" (the
 * year so far, when the month is the open one or December), else "No sales Jan – Mar 2026"
 * (year to date ends with the month shown: a later sale isn't counted, so it isn't "in 2026"). */
export function noSalesLine(month: string, now: Date = new Date()): string {
  const year = month.slice(0, 4);
  if (month >= fmt.currentMonth(now) || month.endsWith("-12")) return `No sales in ${year}`;
  if (month.endsWith("-01")) return `No sales in ${fmt.formatMonth(month, "medium")}`;
  return `No sales Jan – ${fmt.formatMonth(month, "medium")}`;
}
