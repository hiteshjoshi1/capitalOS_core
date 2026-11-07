import type { MoveCause, MoveCauses } from "./api";
import * as fmt from "./format";

/** The backend's none_reason wording (app/valuation/move_causes.py NONE_REASON). */
export const NO_DATA_CAUSE = "No data cause found: a market move";

/** Causes sized at a value (what's new), not at a change. */
const VALUE_CAUSES = new Set(["first_statement", "new_position", "price_fallback"]);

/** Whether a period's causes are worth showing (#289): a big move, or a significant cause. */
export function shouldShowMoveCauses(data: MoveCauses | null | undefined): boolean {
  if (!data) return false;
  return data.is_big_move || data.causes.some((c) => c.significant);
}

/** A cause's size: a value for what's new, a signed change otherwise; null when unknown. */
export function causeAmount(cause: MoveCause, currency: string): string | null {
  if (cause.amount == null) return null;
  return VALUE_CAUSES.has(cause.key) ? fmt.formatMoney(cause.amount, currency) : fmt.formatSignedMoney(cause.amount, currency);
}
