/**
 * Ambient AbortSignal for API calls (#148).
 *
 * `useApiResource` runs each fetcher inside `withAbortSignal(signal, fetcher)`. Every
 * `req()` in lib/api/http.ts that *starts* during that synchronous call picks the signal up,
 * so `() => api.cashDeposits(month, ccy)` (or a `Promise.all` of several calls) is
 * abortable without threading a `signal` argument through ~40 API wrappers.
 *
 * Only calls started synchronously inside `call` see the signal; a call started after an
 * `await` doesn't, and then simply isn't aborted (the hook still ignores its result).
 * This lives outside lib/api(.ts and api/) so tests that `vi.mock("../lib/api")` keep it.
 */
let ambientSignal: AbortSignal | undefined;

export function withAbortSignal<T>(signal: AbortSignal, call: () => Promise<T>): Promise<T> {
  const previous = ambientSignal;
  ambientSignal = signal;
  try {
    return call();
  } finally {
    ambientSignal = previous;
  }
}

/** The signal of the enclosing `withAbortSignal`, if any. Read it synchronously. */
export function currentAbortSignal(): AbortSignal | undefined {
  return ambientSignal;
}

export function isAbortError(err: unknown): boolean {
  // DOMException isn't an Error subclass in every runtime (e.g. jsdom), so match the name.
  return typeof err === "object" && err !== null && (err as { name?: unknown }).name === "AbortError";
}
