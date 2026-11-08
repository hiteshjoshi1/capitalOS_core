/** Where each "This month" bridge line's rows are (#240: a first version links to the page). */
export const BRIDGE_LINKS: Record<string, { to: string; label: string }> = {
  new_money: { to: "/cash", label: "Open cash" },
  markets: { to: "/holdings", label: "Open holdings" },
  fx: { to: "/cash", label: "Open cash by currency" },
  dividends_interest: { to: "/income", label: "Open income" },
  cash_kept: { to: "/cash-flow", label: "Open cash flow" },
  catch_up: { to: "/operations", label: "Open Data Hub" },
  newly_tracked: { to: "/crypto/wallets", label: "Open wallets" },
  unexplained: { to: "/wealth/history", label: "Open history" },
};
