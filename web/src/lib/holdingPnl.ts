import type { StockHolding } from "./api";

/** A holding's unrealised P&L in the base currency (at the rate its value implies), or null
 * without the inputs: the number behind the Profit & Loss cell, for sorting (#396). */
export function holdingPnlBase(holding: StockHolding): number | null {
  if (holding.quantity == null || holding.avg_cost == null || holding.latest_price == null || holding.value == null) {
    return null;
  }
  const nativeValue = holding.quantity * holding.latest_price;
  if (nativeValue <= 0) return null;
  return holding.quantity * (holding.latest_price - holding.avg_cost) * (holding.value / nativeValue);
}
