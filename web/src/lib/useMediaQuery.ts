import { useCallback, useSyncExternalStore } from "react";

/** The width at and below which the shell switches to its phone layout (no sidebar,
 *  bottom nav). Keep in step with the `@media (max-width: 980px)` blocks in App.css. */
export const NARROW_SHELL_QUERY = "(max-width: 980px)";

function mediaQueryList(query: string): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return null;
  }
  return window.matchMedia(query);
}

/** Whether `query` matches now, re-rendering when it changes. Without matchMedia
 *  (jsdom, old browsers) it reports false: the desktop layout. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = mediaQueryList(query);
      if (!list) return () => undefined;
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => mediaQueryList(query)?.matches ?? false,
    () => false,
  );
}
