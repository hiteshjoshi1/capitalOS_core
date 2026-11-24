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

/** #475 (V24): zones offered first, after the current one and this device's. */
export const COMMON_TIMEZONES = ["Asia/Singapore", "Asia/Kolkata"];

/** The current zone, this device's and the common ones, in that order, without repeats. */
export function suggestedTimezones(current?: string | null, device?: string | null): string[] {
  const out: string[] = [];
  for (const zone of [current, device, ...COMMON_TIMEZONES]) {
    if (zone && !out.includes(zone)) out.push(zone);
  }
  return out;
}

const searchKey = (value: string) => value.toLowerCase().replace(/[_/]+/g, " ").trim();

/** Whether a zone's name holds the query, ignoring case, "_" and "/" ("new york" finds
 * America/New_York, "kolkata" Asia/Kolkata). An empty query matches every zone. */
export function matchesTimezone(zone: string, query: string): boolean {
  const q = searchKey(query);
  return !q || searchKey(zone).includes(q);
}

/** First sign-in: a server that says the timezone is not filled yet gets this browser's. */
export function fillTimezoneIfUnset(prefs: UserPreferences | null | undefined): void {
  if (prefs?.timezone_source !== "unset") return;
  const zone = browserTimezone();
  if (!zone) return;
  // Non-fatal: the server keeps using the app's timezone; the next sign-in retries.
  void api.patchPreferences?.({ timezone: zone })?.catch(() => {});
}
