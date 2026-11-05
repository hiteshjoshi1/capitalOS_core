import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { currentAbortSignal } from "../lib/abortScope";
import { clearApiCache, useApiResource } from "../lib/useApiResource";

type Deferred<T> = { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void };
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** A fake API call: resolves when told to, and records the ambient signal it ran under. */
function controllableFetcher<T>() {
  const calls: { key: string; signal: AbortSignal | undefined; d: Deferred<T> }[] = [];
  const make = (key: string) => () => {
    const d = deferred<T>();
    calls.push({ key, signal: currentAbortSignal(), d });
    return d.promise;
  };
  return { calls, make };
}

afterEach(() => {
  clearApiCache();
});

describe("useApiResource", () => {
  it("never shows a slow earlier response under a later key", async () => {
    const f = controllableFetcher<string>();
    const { result, rerender } = renderHook(({ k }) => useApiResource(k, f.make(k)), {
      initialProps: { k: "month:2026-09" },
    });
    expect(result.current.isLoading).toBe(true);

    rerender({ k: "month:2026-10" });
    // October answers first...
    await act(async () => f.calls[1].d.resolve("october"));
    expect(result.current.data).toBe("october");
    // ...then the slow September reply lands. It must not replace October.
    await act(async () => f.calls[0].d.resolve("september"));
    expect(result.current.data).toBe("october");
    expect(result.current.isPlaceholder).toBe(false);
  });

  it("aborts the superseded request when the key changes", async () => {
    const f = controllableFetcher<string>();
    const { rerender } = renderHook(({ k }) => useApiResource(k, f.make(k)), {
      initialProps: { k: "ccy:SGD" },
    });
    const first = f.calls[0].signal;
    expect(first).toBeDefined();
    expect(first?.aborted).toBe(false);

    rerender({ k: "ccy:USD" });
    await waitFor(() => expect(first?.aborted).toBe(true));
    expect(f.calls[1].signal?.aborted).toBe(false);
  });

  it("keeps the previous key's data on screen while the next key loads", async () => {
    const f = controllableFetcher<string>();
    const { result, rerender } = renderHook(({ k }) => useApiResource(k, f.make(k)), {
      initialProps: { k: "a" },
    });
    await act(async () => f.calls[0].d.resolve("A"));
    expect(result.current.data).toBe("A");

    rerender({ k: "b" });
    expect(result.current.data).toBe("A");
    expect(result.current.isPlaceholder).toBe(true);
    expect(result.current.isFetching).toBe(true);
    expect(result.current.isLoading).toBe(false);

    await act(async () => f.calls[1].d.resolve("B"));
    expect(result.current.data).toBe("B");
    expect(result.current.isPlaceholder).toBe(false);
    expect(result.current.isFetching).toBe(false);
  });

  it("does not keep previous data when keepPreviousData is false", async () => {
    const f = controllableFetcher<string>();
    const { result, rerender } = renderHook(
      ({ k }) => useApiResource(k, f.make(k), { keepPreviousData: false }),
      { initialProps: { k: "a" } },
    );
    await act(async () => f.calls[0].d.resolve("A"));
    rerender({ k: "b" });
    expect(result.current.data).toBeUndefined();
    expect(result.current.isLoading).toBe(true);
  });

  it("dedupes two components reading the same key into one request", async () => {
    const fetcher = vi.fn(() => Promise.resolve(3));
    function Reader({ label }: { label: string }) {
      const { data } = useApiResource("alerts", fetcher);
      return <span>{`${label}:${data ?? "-"}`}</span>;
    }
    render(
      <>
        <Reader label="sidebar" />
        <Reader label="page" />
      </>,
    );
    expect(await screen.findByText("sidebar:3")).toBeInTheDocument();
    expect(screen.getByText("page:3")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not abort a shared request while another reader still uses it", async () => {
    const f = controllableFetcher<string>();
    const fetcher = f.make("shared");
    const one = renderHook(() => useApiResource("shared", fetcher));
    const two = renderHook(() => useApiResource("shared", fetcher));
    expect(f.calls).toHaveLength(1);
    one.unmount();
    await new Promise((r) => setTimeout(r, 5));
    expect(f.calls[0].signal?.aborted).toBe(false);
    await act(async () => f.calls[0].d.resolve("ok"));
    expect(two.result.current.data).toBe("ok");
  });

  it("aborts the request when the last reader unmounts", async () => {
    const f = controllableFetcher<string>();
    const { unmount } = renderHook(() => useApiResource("gone", f.make("gone")));
    unmount();
    await waitFor(() => expect(f.calls[0].signal?.aborted).toBe(true));
  });

  it("renders cached data at once on remount and revalidates it", async () => {
    let n = 0;
    const fetcher = vi.fn(() => Promise.resolve(`v${++n}`));
    const first = renderHook(() => useApiResource("cached", fetcher));
    await waitFor(() => expect(first.result.current.data).toBe("v1"));
    first.unmount();

    const second = renderHook(() => useApiResource("cached", fetcher));
    expect(second.result.current.data).toBe("v1");
    expect(second.result.current.isLoading).toBe(false);
    await waitFor(() => expect(second.result.current.data).toBe("v2"));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("skips the refetch while cached data is younger than staleTimeMs", async () => {
    const fetcher = vi.fn(() => Promise.resolve("x"));
    const first = renderHook(() => useApiResource("fresh", fetcher, { staleTimeMs: 60_000 }));
    await waitFor(() => expect(first.result.current.data).toBe("x"));
    first.unmount();
    renderHook(() => useApiResource("fresh", fetcher, { staleTimeMs: 60_000 }));
    await new Promise((r) => setTimeout(r, 5));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("reports an error for the current key and recovers on reload", async () => {
    const fetcher = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error("HTTP 500"))
      .mockResolvedValueOnce("ok");
    const { result } = renderHook(() => useApiResource("flaky", fetcher));
    await waitFor(() => expect(result.current.error?.message).toBe("HTTP 500"));
    expect(result.current.data).toBeUndefined();
    expect(result.current.isLoading).toBe(false);

    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBe("ok");
  });

  it("never shows a previous key's data next to the next key's error", async () => {
    const fetcher = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce("A")
      .mockRejectedValueOnce(new Error("boom"));
    const { result, rerender } = renderHook(({ k }) => useApiResource(k, fetcher), {
      initialProps: { k: "a" },
    });
    await waitFor(() => expect(result.current.data).toBe("A"));
    rerender({ k: "b" });
    await waitFor(() => expect(result.current.error?.message).toBe("boom"));
    expect(result.current.data).toBeUndefined();
    expect(result.current.isPlaceholder).toBe(false);
  });

  it("a reload replaces an in-flight request instead of joining it", async () => {
    const f = controllableFetcher<string>();
    const fetcher = f.make("write");
    const { result } = renderHook(() => useApiResource("write", fetcher));
    let reloaded: Promise<string | undefined>;
    act(() => {
      reloaded = result.current.reload();
    });
    expect(f.calls).toHaveLength(2);
    expect(f.calls[0].signal?.aborted).toBe(true);
    await act(async () => {
      f.calls[1].d.resolve("after-write");
      await reloaded;
    });
    expect(result.current.data).toBe("after-write");
  });

  it("a null key fetches nothing", () => {
    const fetcher = vi.fn(() => Promise.resolve(1));
    const { result } = renderHook(() => useApiResource(null, fetcher));
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeUndefined();
  });

  it("clearApiCache drops data and ignores replies that were in flight", async () => {
    const f = controllableFetcher<string>();
    const first = renderHook(() => useApiResource("user-data", f.make("user-data")));
    act(() => clearApiCache());
    await act(async () => f.calls[0].d.resolve("previous user's numbers"));
    expect(first.result.current.data).toBeUndefined();
  });
});
