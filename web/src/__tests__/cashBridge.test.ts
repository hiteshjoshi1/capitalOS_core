import { describe, expect, it } from "vitest";

import type { CashFlowWaterfall } from "../lib/api";
import { cashBridgeSpanText } from "../lib/cashBridge";

function waterfall(overrides: Partial<CashFlowWaterfall>): CashFlowWaterfall {
  return {
    starting_cash: 10_000,
    snapshot_start_as_of: "2026-10-06T00:00:00+00:00",
    snapshot_start_boundary_at: "2026-11-01T00:00:00+00:00",
    inflows: 0,
    outflows: 0,
    transfers_and_funding: 0,
    investment_and_fx_effects: null,
    other_cash_movements: null,
    snapshot_end_as_of: "2026-11-04T00:00:00+00:00",
    snapshot_end_boundary_at: "2026-12-01T00:00:00+00:00",
    boundary_exact: false,
    availability_message: null,
    ending_cash: 11_000,
    ...overrides,
  };
}

describe("cashBridgeSpanText (#265)", () => {
  it("names the nearest snapshots, and 'the newest so far' for the open month", () => {
    const text = cashBridgeSpanText(
      waterfall({ bridge_available: true, span_start: "2026-10-06", span_end: "2026-11-04", span_basis: "nearest" }),
      "2026-11-07",
    );
    expect(text).toBe("Cash snapshots from 6 Oct 2026 to 4 Nov 2026. The nearest to 1 Nov 2026 and the newest so far.");
  });

  it("names both boundaries for a past month", () => {
    const text = cashBridgeSpanText(
      waterfall({
        bridge_available: true,
        span_start: "2026-01-31",
        span_end: "2026-02-28",
        span_basis: "nearest",
        snapshot_start_boundary_at: "2026-02-01T00:00:00+00:00",
        snapshot_end_boundary_at: "2026-03-01T00:00:00+00:00",
      }),
      "2026-11-07",
    );
    expect(text).toBe("Cash snapshots from 31 Jan 2026 to 28 Feb 2026. The nearest to 1 Feb 2026 and 1 Mar 2026.");
  });

  it("says only the span when the snapshots are on the boundaries", () => {
    const text = cashBridgeSpanText(
      waterfall({ bridge_available: true, span_start: "2026-02-01", span_end: "2026-03-01", span_basis: "exact" }),
      "2026-11-07",
    );
    expect(text).toBe("Cash snapshots from 1 Feb 2026 to 1 Mar 2026.");
  });

  it("is null when the bridge isn't available", () => {
    expect(cashBridgeSpanText(waterfall({ bridge_available: false, availability_message: "No cash snapshot newer" }))).toBeNull();
  });

  it("falls back to boundary_exact for an older API without bridge_available", () => {
    expect(cashBridgeSpanText(waterfall({ boundary_exact: false }))).toBeNull();
    expect(cashBridgeSpanText(waterfall({ boundary_exact: true }), "2026-11-07")).toBe(
      "Cash snapshots from 6 Oct 2026 to 4 Nov 2026.",
    );
  });
});
