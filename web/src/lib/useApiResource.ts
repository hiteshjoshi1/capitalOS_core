/**
 * useApiResource (#148): the one way pages read from the API.
 *
 * - **Keyed cache.** Each resource has a string key that names everything the response
 *   depends on (endpoint, month, currency, ...). Data is stored per key, so a response can
 *   only ever be shown under the key it was fetched for: a slow September reply that lands
 *   after the user switched to October goes into the September entry, never on screen as
 *   October (finding 7.2 in #130).
 * - **Stale-while-revalidate.** A cached key renders at once and is refetched on mount
 *   (`staleTimeMs`, default 0, so a page never shows numbers older than the last visit
 *   without asking the server again).
 * - **Dedupe.** Two components mounting the same key share one request (e.g. the sidebar
 *   and the Alerts page both reading `/alerts/notifications`).
 * - **Abort.** When the last component using a key goes away (unmount, or its key changed)
 *   the in-flight request is aborted. The fetcher runs inside `withAbortSignal`, so every
 *   `api.*` call it starts synchronously carries the signal.
 * - **Keep previous data.** While a new key loads, `data` is the last data this component
 *   showed and `isPlaceholder` is true, so pages dim/annotate instead of blanking to
 *   "Loading..." on every month or currency change (finding 6.4).
 *
 * The cache is module-level; `clearApiCache()` empties it (sign-in, sign-out, tests).
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { isAbortError, withAbortSignal } from "./abortScope";

type Entry = {
  hasData: boolean;
  data: unknown;
  error: Error | null;
  /** ms epoch of the last successful load; 0 = never. */
  updatedAt: number;
  fetching: boolean;
};

type Inflight = {
  controller: AbortController;
  promise: Promise<unknown>;
};

const EMPTY_ENTRY: Entry = { hasData: false, data: undefined, error: null, updatedAt: 0, fetching: false };
/** Unused entries beyond this many are evicted, oldest first. */
const MAX_ENTRIES = 200;

const entries = new Map<string, Entry>();
const inflight = new Map<string, Inflight>();
const refCounts = new Map<string, number>();
const listeners = new Map<string, Set<() => void>>();
/** Bumped by clearApiCache so a request that was in flight across a sign-out can't write back. */
let generation = 0;

function notify(key: string): void {
  listeners.get(key)?.forEach((listener) => listener());
}

function setEntry(key: string, patch: Partial<Entry>): void {
  const current = entries.get(key) ?? EMPTY_ENTRY;
  entries.set(key, { ...current, ...patch });
  notify(key);
}

function subscribeKey(key: string, listener: () => void): () => void {
  let set = listeners.get(key);
  if (!set) {
    set = new Set();
    listeners.set(key, set);
  }
  set.add(listener);
  return () => {
    set.delete(listener);
    if (set.size === 0) listeners.delete(key);
  };
}

function toError(err: unknown): Error {
  return err instanceof Error ? err : new Error(String(err));
}

function evictUnused(): void {
  if (entries.size <= MAX_ENTRIES) return;
  const unused = [...entries.entries()]
    .filter(([key]) => !refCounts.get(key) && !inflight.has(key))
    .sort((a, b) => a[1].updatedAt - b[1].updatedAt);
  for (const [key] of unused) {
    if (entries.size <= MAX_ENTRIES) break;
    entries.delete(key);
  }
}

/**
 * Start (or join) the request for `key`. `force` aborts a request already in flight and
 * starts a new one (a reload after a write must not get a reply that predates the write).
 */
function startFetch<T>(key: string, fetcher: () => Promise<T>, force: boolean): Promise<T> {
  const existing = inflight.get(key);
  if (existing && !force) return existing.promise as Promise<T>;
  existing?.controller.abort();

  const controller = new AbortController();
  const gen = generation;
  let promise: Promise<T>;
  try {
    promise = Promise.resolve(withAbortSignal(controller.signal, fetcher));
  } catch (err: unknown) {
    promise = Promise.reject(err);
  }
  const isCurrent = () => gen === generation && inflight.get(key)?.controller === controller;

  const tracked = promise.then(
    (data) => {
      if (isCurrent()) {
        inflight.delete(key);
        setEntry(key, { hasData: true, data, error: null, updatedAt: Date.now(), fetching: false });
        evictUnused();
      }
      return data;
    },
    (err: unknown) => {
      if (isCurrent()) {
        inflight.delete(key);
        if (isAbortError(err) || controller.signal.aborted) {
          setEntry(key, { fetching: false });
        } else {
          setEntry(key, { error: toError(err), fetching: false });
        }
      }
      throw err;
    },
  );
  inflight.set(key, { controller, promise: tracked });
  // A retry clears the old error, so the page shows "loading" rather than the failure.
  setEntry(key, { fetching: true, error: null });
  return tracked;
}

function retain(key: string): void {
  refCounts.set(key, (refCounts.get(key) ?? 0) + 1);
}

function release(key: string): void {
  const next = (refCounts.get(key) ?? 1) - 1;
  if (next > 0) {
    refCounts.set(key, next);
    return;
  }
  refCounts.delete(key);
  // Deferred: StrictMode's mount -> unmount -> mount, or a key that flips back in the
  // same tick, re-retains before this runs and keeps the request.
  setTimeout(() => {
    if (refCounts.get(key)) return;
    const pending = inflight.get(key);
    if (!pending) return;
    pending.controller.abort();
    inflight.delete(key);
    setEntry(key, { fetching: false });
  }, 0);
}

/**
 * Read `key` through the same cache from an event handler or a page's load effect (#149):
 * joins a request for `key` already in flight (another component, or StrictMode running the
 * effect twice) instead of sending a second one, and stores the answer for every
 * `useApiResource(key)` reader. `force` sends a new request (after a write). While it is
 * pending the key is held, so a reader unmounting meanwhile doesn't abort it.
 */
export async function loadApiResource<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: { force?: boolean } = {},
): Promise<T> {
  retain(key);
  try {
    return await startFetch(key, fetcher, options.force ?? false);
  } finally {
    release(key);
  }
}

/** Forget every cached response and abort every request (sign-in, sign-out, tests). */
export function clearApiCache(): void {
  generation += 1;
  inflight.forEach((pending) => pending.controller.abort());
  inflight.clear();
  const keys = [...entries.keys()];
  entries.clear();
  keys.forEach(notify);
}

export type ApiResourceOptions = {
  /** Skip the refetch on mount when the cached data is younger than this. Default 0. */
  staleTimeMs?: number;
  /** While a new key loads, keep returning the last data. Default true. */
  keepPreviousData?: boolean;
};

export type ApiResource<T> = {
  /** Data for `key`, or (while it loads, with keepPreviousData) the last data shown. */
  data: T | undefined;
  /** The last load of `key` failed. */
  error: Error | null;
  /** Nothing to show yet for this key (first load, no placeholder). */
  isLoading: boolean;
  /** A request for `key` is in flight (first load or a background refresh). */
  isFetching: boolean;
  /** `data` belongs to a previous key and is shown only until `key` loads. */
  isPlaceholder: boolean;
  /** Refetch `key`, ignoring the cache; rejects when the load fails. */
  reload: () => Promise<T | undefined>;
};

/**
 * Read `key` through the shared cache. `fetcher` should call `api.*` and is only invoked
 * when `key` needs loading; it must depend on nothing that isn't encoded in `key`.
 * A `null` key disables the resource (nothing is fetched, `data` is undefined).
 */
export function useApiResource<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  options: ApiResourceOptions = {},
): ApiResource<T> {
  const { staleTimeMs = 0, keepPreviousData = true } = options;

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const subscribe = useCallback(
    (listener: () => void) => (key == null ? () => undefined : subscribeKey(key, listener)),
    [key],
  );
  const getSnapshot = useCallback(() => (key == null ? undefined : entries.get(key)), [key]);
  const entry = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (key == null) return undefined;
    retain(key);
    const cached = entries.get(key);
    const fresh =
      cached?.hasData === true && cached.error == null && Date.now() - cached.updatedAt < staleTimeMs;
    if (!fresh) {
      startFetch(key, () => fetcherRef.current(), false).catch(() => undefined);
    }
    return () => release(key);
  }, [key, staleTimeMs]);

  // Remember the last data this component showed, for keepPreviousData. Updated during
  // render (React's "adjust state when a prop changes" pattern), never from an effect.
  const [previous, setPrevious] = useState<{ key: string; data: T } | null>(null);
  if (key != null && entry?.hasData && (previous?.key !== key || previous.data !== entry.data)) {
    setPrevious({ key, data: entry.data as T });
  }

  const reload = useCallback(async (): Promise<T | undefined> => {
    if (key == null) return undefined;
    return startFetch(key, () => fetcherRef.current(), true);
  }, [key]);

  const hasOwnData = entry?.hasData === true;
  const error = entry?.error ?? null;
  const isPlaceholder = !hasOwnData && error == null && keepPreviousData && previous != null && key != null;
  const data = hasOwnData ? (entry.data as T) : isPlaceholder ? previous.data : undefined;

  return {
    data,
    error,
    isLoading: key != null && data === undefined && error == null,
    // Before the mount effect runs there is no entry yet, but a request is about to start.
    isFetching: key != null && (entry?.fetching ?? !hasOwnData),
    isPlaceholder,
    reload,
  };
}

/** A cache key from its parts: `resourceKey("cashDeposits", month, ccy)`. */
export function resourceKey(...parts: Array<string | number | boolean | null | undefined>): string {
  return parts.map((part) => (part == null ? "" : String(part))).join("|");
}
