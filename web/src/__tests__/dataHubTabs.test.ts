import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { APP_SECTIONS, findActiveSection, findActiveTab } from "../lib/navigation";

// #321 (#309): Data Hub has three tabs; adding and Market data count as Accounts & sources.
describe("Data Hub tabs (#321)", () => {
  const hub = APP_SECTIONS.find((s) => s.id === "operations")!;

  it("shows Inbox · Accounts & sources · Imports", () => {
    expect(hub.tabs.filter((t) => !t.hidden).map((t) => t.label)).toEqual(["Inbox", "Accounts & sources", "Imports"]);
  });

  it.each([
    ["/operations", "Inbox"],
    ["/operations/sources", "Accounts & sources"],
    ["/accounts/new", "Accounts & sources"],
    ["/market-data", "Accounts & sources"],
    ["/ingest", "Imports"],
  ])("%s is under Data Hub → %s", (path, tab) => {
    expect(findActiveSection(path)?.id).toBe("operations");
    expect(findActiveTab(hub, path)?.label).toBe(tab);
  });

  it("keeps /crypto (add a wallet) in Data Hub and /crypto/holdings in Wealth", () => {
    expect(findActiveSection("/crypto")?.id).toBe("operations");
    expect(findActiveSection("/crypto/holdings")?.id).toBe("wealth");
  });

  it("redirects the old platforms page to Settings → Admin", () => {
    const main = readFileSync(resolve(__dirname, "../main.tsx"), "utf8");
    expect(main).toMatch(/path="\/platforms" element=\{<Navigate to="\/settings\/admin" replace \/>\}/);
    expect(main).toContain('path="/settings/admin"');
  });
});
