/**
 * Shared base currency (#150, review #130 finding 7.3). One value for the whole app:
 * pick USD on Stocks and Cash shows USD too, and the choice survives a reload.
 *
 * A tiny external store (useSyncExternalStore) rather than a React context provider, so
 * every component that reads it, the header picker and the page alike, shares one value
 * even when rendered on its own in a test. It is persisted per browser in localStorage
 * and follows changes made in another tab.
 *
 * Since #202 it is also saved on the server (`user_preferences.base_currency`), so it
 * follows the user across devices: the per-browser value is the first paint, and the
 * server's value wins once the session loads (`syncServerBaseCurrency`). A choice made
 * in the picker or in Settings is saved to both.
 */
import { useSyncExternalStore } from "react";

import { api } from "../lib/api";
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

/** The value this browser has explicitly saved, or null (nothing saved, or unreadable). */
function storedBaseCurrencyChoice(): BaseCurrencyCode | null {
  try {
    const stored = window.localStorage.getItem(BASE_CURRENCY_STORAGE_KEY);
    return isBaseCurrency(stored) ? stored : null;
  } catch {
    return null;
  }
}

/** The value the server is known to hold (last applied from it or saved to it). */
let serverValue: BaseCurrencyCode | null = null;

/** Set the shared value in this browser only (no server write). */
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

/** The user picked a base currency: set it here and save it on the server (#202). */
export function chooseBaseCurrency(currency: string): void {
  if (!isBaseCurrency(currency)) return;
  setBaseCurrency(currency);
  if (serverValue === currency || !api.isAuthenticated?.()) return;
  serverValue = currency;
  void api.patchPreferences?.({ base_currency: currency })?.catch(() => {
    // Non-fatal: the per-browser value still holds; the next sign-in retries.
    serverValue = null;
  });
}

/**
 * Apply the server's saved base currency after sign-in (#202): it wins over this
 * browser's value. When the server has none yet (`null`), this browser's saved choice,
 * if any, is sent up so the user's other devices get it. `undefined` (a server from
 * before #202) leaves everything as it is.
 */
export function syncServerBaseCurrency(value: string | null | undefined): void {
  if (value === undefined) return;
  if (isBaseCurrency(value)) {
    serverValue = value;
    setBaseCurrency(value);
    return;
  }
  serverValue = null;
  const local = storedBaseCurrencyChoice();
  if (local) chooseBaseCurrency(local);
}

/** Forget what the server holds (sign-out), so the next user's value is applied fresh. */
export function resetServerBaseCurrency(): void {
  serverValue = null;
}

/** `[baseCurrency, chooseBaseCurrency]`, shared by every page and the header picker. */
export function useBaseCurrency(): readonly [BaseCurrencyCode, (currency: string) => void] {
  const baseCurrency = useSyncExternalStore(subscribe, readStoredBaseCurrency, () => DEFAULT_BASE_CURRENCY);
  return [baseCurrency, chooseBaseCurrency] as const;
}
