// The "+ Add" stepper (#319): what → where → details → first data. Pure helpers, so each
// step's rules (which platforms fit, the defaults, what's still missing) are testable alone.
import type { Platform } from "./api";

export type AddKind = "bank" | "card" | "broker" | "exchange" | "fund" | "loan" | "wallet";
export type WalletChain = "evm" | "solana";

export type AddKindMeta = {
  id: AddKind;
  label: string;
  hint: string;
  /** The account's account_type; null for a self-custody wallet (a crypto_wallets row, not an account). */
  accountType: string | null;
  /** Platform types offered first in "where"; other platforms stay one tick away. */
  platformTypes: string[];
};

export const ADD_KINDS: AddKindMeta[] = [
  { id: "bank", label: "Bank account", hint: "Savings or current account; you upload its statements.", accountType: "BANK", platformTypes: ["BANK"] },
  { id: "card", label: "Credit card", hint: "What you owe and pay, from the card's statements.", accountType: "CREDIT_CARD", platformTypes: ["CARD_ISSUER", "BANK"] },
  { id: "broker", label: "Brokerage", hint: "Stocks and funds held with a broker.", accountType: "BROKER", platformTypes: ["BROKER"] },
  { id: "fund", label: "Mutual funds", hint: "Funds held directly with a fund house or bank.", accountType: "MUTUAL_FUND", platformTypes: ["BROKER", "BANK"] },
  { id: "exchange", label: "Crypto exchange", hint: "Coins held on an exchange account.", accountType: "EXCHANGE", platformTypes: ["EXCHANGE"] },
  { id: "loan", label: "Loan", hint: "A loan's balance, from its statements.", accountType: "LOAN", platformTypes: ["BANK"] },
  { id: "wallet", label: "Crypto wallet", hint: "Your own wallet: connect it and sign to prove it's yours.", accountType: null, platformTypes: [] },
];

export const STEP_LABELS = ["What", "Where", "Details", "First data"] as const;

/** The kinds the API can create: account kinds whose type /accounts/options lists, plus wallets. */
export function availableKinds(accountTypes: string[]): AddKindMeta[] {
  return ADD_KINDS.filter((k) => k.accountType === null || accountTypes.includes(k.accountType));
}

export function kindMeta(kind: AddKind | null): AddKindMeta | null {
  return ADD_KINDS.find((k) => k.id === kind) ?? null;
}

export function parseKind(value: string | null): AddKind | null {
  return ADD_KINDS.some((k) => k.id === value) ? (value as AddKind) : null;
}

/** Platforms whose type fits the kind, by name; all of them when `showAll` (or none fit). */
export function platformsForKind(platforms: Platform[], kind: AddKindMeta, showAll: boolean): Platform[] {
  const fit = platforms.filter((p) => kind.platformTypes.includes(p.platform_type));
  const list = showAll || fit.length === 0 ? platforms : fit;
  return [...list].sort((a, b) => a.name.localeCompare(b.name));
}

const COUNTRY_CURRENCY: Record<string, string> = {
  SG: "SGD",
  IN: "INR",
  US: "USD",
  HK: "HKD",
  GB: "GBP",
  UK: "GBP",
  AU: "AUD",
  MY: "MYR",
  JP: "JPY",
  CH: "CHF",
  CA: "CAD",
  AE: "AED",
};

/** The platform's home currency, or "" when its country doesn't say (GLOBAL, unknown). */
export function defaultCurrency(country: string | null | undefined): string {
  return COUNTRY_CURRENCY[(country ?? "").toUpperCase()] ?? "";
}

/** "Citibank Credit card": the platform's name and the kind, which the user can edit. */
export function defaultAccountName(platform: Platform, kind: AddKindMeta): string {
  return `${platform.name} ${kind.label}`;
}

/** A platform code from its name ("DBS Bank" → "DBS_BANK"), matching the API's ^[A-Z0-9_]+$. */
export function deriveCode(name: string): string {
  return name
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 24);
}

export type AccountDraft = { name: string; currency: string; country: string };

/** Defaults for the details step, from the platform (#319: "defaults from the platform"). */
export function draftFromPlatform(platform: Platform, kind: AddKindMeta): AccountDraft {
  const country = /^[A-Z]{2,3}$/.test(platform.country) ? platform.country : "";
  return { name: defaultAccountName(platform, kind), currency: defaultCurrency(platform.country), country };
}

// What each step still needs, in words: the stepper shows these instead of a dead button.

export function whereMissing(kind: AddKindMeta, platformId: number | null, chain: WalletChain | null): string[] {
  if (kind.accountType === null) return chain ? [] : ["pick the wallet's chain"];
  return platformId ? [] : ["pick where the account is (a platform)"];
}

export function detailsMissing(draft: AccountDraft): string[] {
  const missing: string[] = [];
  if (!draft.name.trim()) missing.push("a name");
  if (!/^[A-Z]{3}$/.test(draft.currency.trim().toUpperCase())) missing.push("a 3-letter currency (e.g. SGD)");
  const country = draft.country.trim();
  if (country && !/^[A-Z]{2,3}$/.test(country.toUpperCase())) missing.push("a 2-letter country code (e.g. SG), or leave it blank");
  return missing;
}

export type PlatformDraftFields = { code: string; name: string; platform_type: string; country: string };

export function platformMissing(draft: PlatformDraftFields): string[] {
  const missing: string[] = [];
  if (!draft.name.trim()) missing.push("the platform's name");
  if (!/^[A-Z0-9_]+$/.test(draft.code.trim().toUpperCase())) missing.push("a code (letters, digits, _)");
  if (!draft.platform_type) missing.push("its type");
  if (!/^[A-Z]{2,3}$/.test(draft.country.trim().toUpperCase())) missing.push("its country (e.g. SG)");
  return missing;
}

/** "a name and a currency" / "a name, a currency and a country". */
export function joinMissing(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
