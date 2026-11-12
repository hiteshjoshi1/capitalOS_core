import type { SinceLastVisit } from "./api";

/** A net-worth change smaller than this (base currency) isn't news (#408, U3). */
export const SINCE_VISIT_CHANGE_MIN = 1;

/** Whether "Since your last visit" has anything to say: a real change, imports, or actions. */
export function hasNews(data: SinceLastVisit | null | undefined): boolean {
  if (!data || data.first_visit) return false;
  return (
    Math.abs(data.change ?? 0) >= SINCE_VISIT_CHANGE_MIN ||
    (data.imports_since ?? 0) > 0 ||
    (data.needs_action ?? 0) > 0
  );
}
