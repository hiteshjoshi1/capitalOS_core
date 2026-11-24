import type { CashBankBrokerView, CashDeposits } from "./api";

/**
 * #473 (V14): the page shows bank and broker cash, the cash net worth counts; stablecoins are
 * their own line (net worth counts them under Crypto, D-42). The server sends it as
 * `bank_broker`; an older API without it gets the headline as the total less its stablecoins.
 */
export function bankBrokerCash(deposits: CashDeposits): CashBankBrokerView {
  if (deposits.bank_broker) return deposits.bank_broker;
  const total = (deposits.current_total ?? 0) - (deposits.current_stablecoin_total ?? 0);
  const snapshotTotal = (deposits.snapshot_total ?? 0) - (deposits.snapshot_stablecoin_total ?? 0);
  const deltaAbs = total - snapshotTotal;
  return {
    total,
    snapshot_total: snapshotTotal,
    delta_abs: deltaAbs,
    delta_pct: snapshotTotal > 0 ? deltaAbs / snapshotTotal : null,
    items: deposits.items,
    currency_breakdown: deposits.currency_breakdown ?? [],
    snapshot_missing: deposits.snapshot_missing ?? false,
  };
}
