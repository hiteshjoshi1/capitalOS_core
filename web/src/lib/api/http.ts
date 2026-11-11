// The HTTP client: API base, access token, refresh and errors (split out of lib/api.ts, #368).
import { currentAbortSignal, isAbortError } from "../abortScope";
import type { AuthSession } from "./types/auth";

export function resolveApiBase(
  rawApiBase?: string,
  locationLike?: { protocol?: string; hostname?: string } | null,
  rawApiPort?: string,
): string {
  const explicit = rawApiBase?.trim();
  if (explicit) {
    return explicit.replace(/\/+$/, "");
  }

  const port = rawApiPort?.trim() || "8000";
  const currentLocation =
    locationLike ?? (typeof window !== "undefined" ? window.location : null);
  const hostname = currentLocation?.hostname?.trim();
  const protocol = currentLocation?.protocol === "https:" ? "https:" : "http:";
  if (hostname) {
    return `${protocol}//${hostname}:${port}`;
  }
  return `http://localhost:${port}`;
}

const RAW_API_BASE = import.meta.env.VITE_API_BASE as string | undefined;
const RAW_API_PORT = import.meta.env.VITE_API_PORT as string | undefined;
export const API_BASE = resolveApiBase(RAW_API_BASE, null, RAW_API_PORT);
let accessTokenMemory: string | null = null;
let refreshInFlight: Promise<AuthSession | null> | null = null;
let authFailureHandler: (() => void) | null = null;

/** Where "Sign in with Google" sends the browser (#358): a full-page navigation, not a fetch. */
export function googleSignInUrl(next: string): string {
  return `${API_BASE}/auth/google/start?next=${encodeURIComponent(next)}`;
}

export function getAccessToken(): string | null {
  return accessTokenMemory;
}

export function setAccessToken(token: string | null): void {
  accessTokenMemory = token;
}

export function setAuthFailureHandler(handler: (() => void) | null): void {
  authFailureHandler = handler;
}

function notifyAuthFailure(): void {
  authFailureHandler?.();
}

export function buildHeaders(
  initHeaders?: HeadersInit,
  opts?: { includeJsonContentType?: boolean; skipAuth?: boolean },
): Headers {
  const headers = new Headers(initHeaders);
  if (opts?.includeJsonContentType !== false && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!opts?.skipAuth) {
    const token = getAccessToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

export type RequestOptions = { skipAuth?: boolean; skipRefreshRetry?: boolean };

type ApiValidationDetail = {
  loc?: Array<string | number>;
  msg?: string;
};

function formatApiValidationMessage(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }

  // A structured refusal (e.g. an upload sent to the wrong account, #180).
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message.trim();
  }

  if (!Array.isArray(detail)) {
    return null;
  }

  const messages = detail
    .map((item) => {
      const entry = item as ApiValidationDetail;
      const msg = typeof entry.msg === "string" ? entry.msg.trim() : "";
      if (!msg) return null;

      const field = Array.isArray(entry.loc)
        ? entry.loc
            .filter((part) => typeof part === "string")
            .filter((part) => part !== "body")
            .join(".")
        : "";
      return field ? `${field}: ${msg}` : msg;
    })
    .filter((message): message is string => Boolean(message));

  if (!messages.length) {
    return null;
  }
  return messages.join("; ");
}

export function formatHttpError(status: number, rawText: string): string {
  const text = rawText.trim();
  if (!text) {
    return `Request failed (${status}).`;
  }

  try {
    const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown };
    const detailMessage = formatApiValidationMessage(parsed.detail);
    if (detailMessage) return detailMessage;
    if (typeof parsed.message === "string" && parsed.message.trim()) return parsed.message.trim();
  } catch {
    // Not JSON, fall through to plain text handling.
  }

  if (status >= 500) return "Server error. Please try again.";
  return text;
}

/**
 * Thrown when a session is definitively invalid (401 from the server).
 * Distinct from transient network or server errors.
 */
export class AuthSessionExpiredError extends Error {
  constructor(message = "Session expired. Please sign in again.") {
    super(message);
    this.name = "AuthSessionExpiredError";
  }
}

async function callRefreshEndpoint(): Promise<AuthSession | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: buildHeaders(undefined, { includeJsonContentType: false, skipAuth: true }),
    });
    if (!res.ok) {
      if (res.status === 401) {
        // Definitive auth failure: the session is truly invalid.
        setAccessToken(null);
        notifyAuthFailure();
      }
      // For 5xx or other transient errors, don't clear auth state.
      return null;
    }
    const payload = (await res.json()) as AuthSession;
    if (!payload?.access_token) {
      setAccessToken(null);
      notifyAuthFailure();
      return null;
    }
    setAccessToken(payload.access_token);
    return payload;
  } catch {
    // Network/transport error: treat as transient. Do not force logout.
    return null;
  }
}

function refreshSession(): Promise<AuthSession | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = callRefreshEndpoint().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function refreshAccessToken(): Promise<string | null> {
  const session = await refreshSession();
  return session?.access_token ?? null;
}

export async function refreshAccessTokenNow(): Promise<string | null> {
  return refreshAccessToken();
}

/**
 * Same deduped refresh as refreshAccessTokenNow(), but resolves to the whole response:
 * since #146 /auth/refresh also carries `user` and `preferences`, so a cold load needs
 * this one request instead of refresh -> /auth/me -> /auth/preferences.
 */
export async function refreshSessionNow(): Promise<AuthSession | null> {
  return refreshSession();
}

export async function req<T>(path: string, init?: RequestInit, opts: RequestOptions = {}): Promise<T> {
  // Read synchronously, before the first await (#148): see lib/abortScope.ts.
  const signal = init?.signal ?? currentAbortSignal();
  const execute = async (): Promise<Response> => {
    try {
      const { headers: initHeaders, ...restInit } = init ?? {};
      return await fetch(`${API_BASE}${path}`, {
        credentials: "include",
        ...restInit,
        ...(signal ? { signal } : {}),
        headers: buildHeaders(initHeaders, { includeJsonContentType: true, skipAuth: opts.skipAuth }),
      });
    } catch (err: unknown) {
      // An aborted request (a superseded month/currency, or the page went away) is not
      // an unreachable API: let the caller see the AbortError as-is.
      if (isAbortError(err)) throw err;
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`, { cause: err });
    }
  };

  let res = await execute();
  let sessionExpired = false;
  if (res.status === 401 && !opts.skipAuth && !opts.skipRefreshRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await execute();
    } else {
      sessionExpired = true;
    }
  }
  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401) {
      if (!opts.skipAuth && sessionExpired) {
        throw new AuthSessionExpiredError("Your session expired. Please sign in again.");
      }
      if (opts.skipAuth) {
        // e.g. /auth/refresh returned 401 → truly invalid session
        throw new AuthSessionExpiredError(formatHttpError(res.status, text));
      }
    }
    throw new Error(formatHttpError(res.status, text));
  }
  return res.json() as Promise<T>;
}
