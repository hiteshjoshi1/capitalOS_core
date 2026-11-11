import type { Account, UploadDetect } from "./api";

// #399 (U27): the account picker grouped by kind, closed accounts last.
const ACCOUNT_GROUPS: [string, string][] = [
  ["BANK", "Bank accounts"],
  ["CREDIT_CARD", "Credit cards"],
  ["BROKER", "Brokers"],
  ["MUTUAL_FUND", "Funds"],
  ["EXCHANGE", "Exchanges"],
  ["WALLET", "Wallets"],
  ["LOAN", "Loans"],
];

export function groupAccounts(accounts: Account[]): { label: string; accounts: Account[] }[] {
  const byName = (a: Account, b: Account) =>
    `${a.platform} ${a.name}`.localeCompare(`${b.platform} ${b.name}`, undefined, { sensitivity: "base" });
  const open = accounts.filter((a) => !a.closed_on);
  const known = new Set(ACCOUNT_GROUPS.map(([type]) => type));
  const groups = ACCOUNT_GROUPS.map(([type, label]) => ({
    label,
    accounts: open.filter((a) => (a.account_type || "").toUpperCase() === type).sort(byName),
  }));
  groups.push({ label: "Other", accounts: open.filter((a) => !known.has((a.account_type || "").toUpperCase())).sort(byName) });
  groups.push({ label: "Closed", accounts: accounts.filter((a) => a.closed_on).sort(byName) });
  return groups.filter((g) => g.accounts.length > 0);
}

/** One line under the picker after a file is chosen: what the file is and which account fits. */
export function detectNote(d: UploadDetect | null, accounts: Account[], accountId: string): string | null {
  if (!d) return null;
  if (!d.recognised) return "Format not recognised yet: pick the account; the upload will say if it doesn't fit.";
  const what = d.file_label ?? "known statement";
  const chosen = accounts.find((a) => String(a.id) === accountId);
  const fits = chosen ? d.candidate_account_ids.includes(chosen.id) : false;
  if (chosen && fits) return `Looks like a ${what}: matches ${chosen.name}.`;
  if (chosen && d.candidate_account_ids.length > 0) {
    const names = accounts.filter((a) => d.candidate_account_ids.includes(a.id)).map((a) => a.name);
    return `Looks like a ${what}, which fits ${names.join(" or ")}, not ${chosen.name}.`;
  }
  if (d.candidate_account_ids.length > 1) return `Looks like a ${what}: pick which account.`;
  if (d.candidate_account_ids.length === 0) return `Looks like a ${what}, but none of your open accounts fits it. Add one first.`;
  return `Looks like a ${what}.`;
}
