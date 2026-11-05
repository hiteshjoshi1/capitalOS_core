import { describe, expect, it } from "vitest";

import { describeSeries, describeShares } from "../lib/chartA11y";

describe("chart descriptions (#151)", () => {
  it("reads out shares", () => {
    expect(describeShares("Cash by account", [{ label: "DBS", percent: 62.5 }, { label: "OCBC", percent: 37.5 }])).toBe(
      "Cash by account: DBS 62.5%, OCBC 37.5%",
    );
  });
  it("says when there is no data", () => {
    expect(describeShares("Allocation", [])).toBe("Allocation: no data");
  });
  it("caps long lists", () => {
    const items = Array.from({ length: 10 }, (_, i) => ({ label: `M${i}`, value: `${i}` }));
    expect(describeSeries("Trend", items)).toMatch(/M7 7, and 2 more$/);
  });
});
