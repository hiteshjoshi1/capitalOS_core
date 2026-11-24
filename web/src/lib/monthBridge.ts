import type { BridgeLine } from "./api";

/** Where each "This month" bridge line's rows are (#240: a first version links to the page). */
export const BRIDGE_LINKS: Record<string, { to: string; label: string }> = {
  new_money: { to: "/cash", label: "Open cash" },
  markets: { to: "/holdings", label: "Open holdings" },
  fx: { to: "/cash", label: "Open cash by currency" },
  dividends_interest: { to: "/income", label: "Open dividends" },
  cash_kept: { to: "/cash-flow", label: "Open cash flow" },
  catch_up: { to: "/operations", label: "Open Data Hub" },
  // No /crypto/wallets page: wallets and accounts are listed in Accounts & sources (#319).
  newly_tracked: { to: "/operations/sources", label: "Open accounts & sources" },
  unexplained: { to: "/wealth/history", label: "Open history" },
};

/** #475 (V9): "New money in" shows only when there is some. A period with no deposits,
 * withdrawals or estimated broker trades (status ok, every part zero) drops the line instead
 * of a permanent "S$ 0"; the bridge still adds up, the line was zero. Its note (transfers from
 * your own accounts: not new money) goes with it. A partial line (an estimate) always shows. */
export function isShownBridgeLine(line: BridgeLine): boolean {
  if (line.key !== "new_money" || line.status !== "ok") return true;
  const zero = (amount: number | null | undefined) => Math.abs(amount ?? 0) < 0.5;
  return !(zero(line.amount) && line.parts.every((part) => zero(part.amount)));
}
