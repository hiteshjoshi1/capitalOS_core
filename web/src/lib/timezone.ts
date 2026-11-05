/**
 * The user's home timezone (#202). Months, month-end anchors and History follow it on
 * the server; it is a setting (Settings), not the device's current zone, so travelling
 * doesn't move month boundaries. A new account starts without one, and the first
 * sign-in fills it from this browser.
 */
import { api, type UserPreferences } from "./api";

/** This browser's IANA timezone, or null when the browser doesn't say. */
export function browserTimezone(): string | null {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return typeof zone === "string" && zone ? zone : null;
  } catch {
    return null;
  }
}

/** Every IANA timezone the browser knows (sorted), plus `include` when it is missing. */
export function timezoneOptions(include?: string | null): string[] {
  const supportedValuesOf = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
  let zones: string[];
  try {
    zones = supportedValuesOf ? supportedValuesOf("timeZone") : [];
  } catch {
    zones = [];
  }
  const all = new Set(zones);
  if (include) all.add(include);
  const browser = browserTimezone();
  if (browser) all.add(browser);
  return [...all].sort();
}

/** First sign-in: a server that says the timezone is not filled yet gets this browser's. */
export function fillTimezoneIfUnset(prefs: UserPreferences | null | undefined): void {
  if (prefs?.timezone_source !== "unset") return;
  const zone = browserTimezone();
  if (!zone) return;
  // Non-fatal: the server keeps using the app's timezone; the next sign-in retries.
  void api.patchPreferences?.({ timezone: zone })?.catch(() => {});
}
