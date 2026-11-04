/**
 * Shared base currency (#150, review #130 finding 7.3). One value for the whole app:
 * pick USD on Stocks and Cash shows USD too, and the choice survives a reload.
 *
 * A tiny external store (useSyncExternalStore) rather than a React context provider, so
 * every component that reads it, the header picker and the page alike, shares one value
 * even when rendered on its own in a test. It is persisted per browser in localStorage
 * and follows changes made in another tab.
 *
 * Saving it as a server preference (as theme and accent are) needs a `base_currency`
 * column on `user_preferences`, i.e. a migration; that is proposed in the PR instead.
 */
import { useSyncExternalStore } from "react";

import { DEFAULT_BASE_CURRENCY, isBaseCurrency, type BaseCurrencyCode } from "../lib/format";

export const BASE_CURRENCY_STORAGE_KEY = "capitalos.baseCurrency";

const listeners = new Set<() => void>();
/** Used only when localStorage is unavailable (private mode, blocked storage). */
let memoryValue: BaseCurrencyCode = DEFAULT_BASE_CURRENCY;

export function readStoredBaseCurrency(): BaseCurrencyCode {
  try {
    const stored = window.localStorage.getItem(BASE_CURRENCY_STORAGE_KEY);
    return isBaseCurrency(stored) ? stored : DEFAULT_BASE_CURRENCY;
  } catch {
    return memoryValue;
  }
}

export function setBaseCurrency(currency: string): void {
  if (!isBaseCurrency(currency)) return;
  memoryValue = currency;
  try {
    window.localStorage.setItem(BASE_CURRENCY_STORAGE_KEY, currency);
  } catch {
    // Storage blocked: the choice still holds for this session.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === BASE_CURRENCY_STORAGE_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** `[baseCurrency, setBaseCurrency]`, shared by every page and the header picker. */
export function useBaseCurrency(): readonly [BaseCurrencyCode, (currency: string) => void] {
  const baseCurrency = useSyncExternalStore(subscribe, readStoredBaseCurrency, () => DEFAULT_BASE_CURRENCY);
  return [baseCurrency, setBaseCurrency] as const;
}
