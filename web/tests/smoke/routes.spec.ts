import { test, expect } from "@playwright/test";
import { APP_SECTIONS } from "../../src/lib/navigation";
import { SMOKE_ROUTES } from "./smoke";

// A page added to the navigation must be smoke-tested and screenshotted too (#73): add it to
// MAIN_ROUTES (tests/e2e/helpers/pages.ts), then `make e2e-smoke-update` for its baselines.
test("every navigation target is in the smoke routes", () => {
  const targets = new Set<string>();
  for (const section of APP_SECTIONS) {
    targets.add(section.to);
    for (const tab of section.tabs) if (!tab.hidden) targets.add(tab.to);
  }
  const missing = [...targets].filter((to) => !SMOKE_ROUTES.includes(to)).sort();
  expect(missing).toEqual([]);
});
