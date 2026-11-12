import { describe, expect, it } from "vitest";

import { APP_SECTIONS } from "../lib/navigation";
import { BRIDGE_LINKS } from "../lib/monthBridge";

describe("Dividends route (#267, renamed in #423)", () => {
  it("names the Wealth tab Dividends (#423) and points it at /income, matching the old /dividends path", () => {
    const wealth = APP_SECTIONS.find((section) => section.id === "wealth");
    const tab = wealth?.tabs.find((t) => t.to === "/income");
    expect(tab?.label).toBe("Dividends");
    expect(tab?.matchPaths).toContain("/dividends");
    expect(wealth?.tabs.some((t) => t.label === "Income")).toBe(false);
  });

  it("sends the This-month bridge's dividends and interest line to the Dividends page", () => {
    expect(BRIDGE_LINKS.dividends_interest.to).toBe("/income");
  });
});
