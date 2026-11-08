import type { CreditCardBalanceItem, CreditCardBalancePeriod } from "./api";
import * as fmt from "./format";

/** Card amounts with their cents (#300): a balance is checked to the cent. */
export function money(value: number | null | undefined, currency: string): string {
  return fmt.formatMoney(value, currency, { decimals: 2 });
}

/** "Owes S$ 674.98", or "In credit S$ 150.00" for an overpaid card. */
export function owedLabel(card: Pick<CreditCardBalanceItem, "owed_now" | "currency">): string {
  return card.owed_now < -0.005
    ? `In credit ${money(-card.owed_now, card.currency)}`
    : `Owes ${money(card.owed_now, card.currency)}`;
}

/** What a flagged statement's difference most likely means. */
export function differenceReason(period: CreditCardBalancePeriod, currency: string): string | null {
  if (!period.flagged || period.difference == null) return null;
  // The ledger's own explanation when it has one (#308): charges after the last upload, etc.
  if (period.note) return period.note;
  const amount = money(Math.abs(period.difference), currency);
  if (period.transaction_count === 0) {
    return `No transactions between these dates: a statement is probably missing (${amount} unaccounted for).`;
  }
  return period.difference > 0
    ? `The bank says ${amount} more is owed than your transactions add up to: a charge, fee or interest you don't have, or a missing upload.`
    : `The bank says ${amount} less is owed than your transactions add up to: a payment or refund you don't have, or a transaction counted twice.`;
}

