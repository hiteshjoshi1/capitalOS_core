import { describe, expect, it } from "vitest";

import { computeDueStatus } from "../lib/dueStatus";

// #352: a card's due date is only one a statement printed (or configured); never guessed.
describe("computeDueStatus", () => {
  const today = new Date("2026-11-20T00:00:00Z");

  it("says the due date is unknown when there is none", () => {
    expect(computeDueStatus({ dueDate: null, unknownLabel: "Due date unknown" }, today)).toEqual({
      tone: "not-synced", label: "Due date unknown", daysUntil: null,
    });
    expect(computeDueStatus({ dueDate: null }, today).label).toBe("Not synced");
  });

  it("is paid once the server says the statement is covered, even past the date", () => {
    expect(computeDueStatus({ dueDate: "2026-11-10", paymentStatus: "paid" }, today)).toEqual({
      tone: "normal", label: "Paid", daysUntil: null,
    });
  });

  it("is overdue or due soon by date otherwise", () => {
    expect(computeDueStatus({ dueDate: "2026-11-10", paymentStatus: "overdue" }, today).tone).toBe("overdue");
    expect(computeDueStatus({ dueDate: "2026-11-23" }, today)).toMatchObject({ tone: "warn", daysUntil: 3 });
  });
});
