import { useEffect, useState } from "react";

import { currentMonth } from "./format";

const SELECTED_MONTH_STORAGE_KEY = "capitalos.selectedMonth";
const MONTH_PATTERN = /^\d{4}-\d{2}$/;

/** The current month as `YYYY-MM` (one implementation: lib/format's `currentMonth`). */
export function currentMonthYYYYMM() {
  return currentMonth();
}

/** `month` (`YYYY-MM`) moved by `delta` months. */
export function shiftMonth(month: string, delta: number): string {
  const [yearRaw, monthRaw] = month.split("-");
  const dt = new Date(Date.UTC(Number(yearRaw), Number(monthRaw) - 1 + delta, 1));
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** The month whose month-end a past-month view shows: the month before its anchor date
 * (`net_worth_boundary_at`, or the crypto summary's `as_of`). With SNAPSHOT_DAY=1 that is the
 * selected month; before a later SNAPSHOT_DAY it is the month before (#232, D-55). */
export function snapshotMonthOf(boundaryAt: string | null | undefined, fallbackMonth: string): string {
  return boundaryAt && MONTH_PATTERN.test(boundaryAt.slice(0, 7)) ? shiftMonth(boundaryAt.slice(0, 7), -1) : fallbackMonth;
}

/** The last day a month-end snapshot closes: the day before its anchor date
 * (`net_worth_boundary_at`), as `YYYY-MM-DD`. With SNAPSHOT_DAY=1, October's month-end
 * (anchor 1 Nov) is "31 Oct close" (#241). Null without a boundary. */
export function monthEndCloseDate(boundaryAt: string | null | undefined): string | null {
  const match = boundaryAt ? /^(\d{4})-(\d{2})-(\d{2})/.exec(boundaryAt) : null;
  if (!match) return null;
  const day = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) - 1));
  return day.toISOString().slice(0, 10);
}

/** Whether `month` is before the current month: a page following it shows that month-end
 * snapshot rather than live data (#223). The same test as MonthControl's "Past month" callout. */
export function isPastMonth(month: string): boolean {
  return month < currentMonthYYYYMM();
}

function isValidMonth(value: string | null): value is string {
  return value != null && MONTH_PATTERN.test(value);
}

export function readSelectedMonth(storageKey = SELECTED_MONTH_STORAGE_KEY) {
  if (typeof window === "undefined") {
    return currentMonthYYYYMM();
  }

  const storedMonth = window.localStorage.getItem(storageKey);
  return isValidMonth(storedMonth) ? storedMonth : currentMonthYYYYMM();
}

export function useSelectedMonth(storageKey = SELECTED_MONTH_STORAGE_KEY) {
  const [month, setMonth] = useState<string>(() => readSelectedMonth(storageKey));

  useEffect(() => {
    window.localStorage.setItem(storageKey, month);
  }, [month, storageKey]);

  return [month, setMonth] as const;
}
