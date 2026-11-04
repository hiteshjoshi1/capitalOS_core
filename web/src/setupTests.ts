import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { clearApiCache } from "./lib/useApiResource";

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
}

// One hook, in this order: unmount first, then empty the API cache (#148), which is
// module-level. Separate afterEach hooks run in reverse order, so clearing the cache
// would re-render still-mounted pages and start a request the next test then joins.
afterEach(() => {
  cleanup();
  clearApiCache();
});

// The shared base currency (#150) is per browser: start every test from the default.
afterEach(() => {
  window.localStorage.removeItem("capitalos.baseCurrency");
});
