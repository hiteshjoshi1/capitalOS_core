import { describe, expect, it } from "vitest";

import { APP_SECTIONS } from "../lib/navigation";
import { BRIDGE_LINKS } from "../lib/monthBridge";

describe("Income route (#267)", () => {
  it("names the Wealth tab Income and points it at /income, matching the old /dividends path", () => {
    const wealth = APP_SECTIONS.find((section) => section.id === "wealth");
    const tab = wealth?.tabs.find((t) => t.to === "/income");
    expect(tab?.label).toBe("Income");
    expect(tab?.matchPaths).toContain("/dividends");
    expect(wealth?.tabs.some((t) => t.label === "Dividends")).toBe(false);
  });

  it("sends the This-month bridge's dividends and interest line to Income", () => {
    expect(BRIDGE_LINKS.dividends_interest.to).toBe("/income");
  });
});
