import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MonthControl from "../components/MonthControl";

describe("MonthControl", () => {
  it("opens the native month picker when the visible pill is clicked", () => {
    const showPicker = vi.fn();
    const inputPrototype = HTMLInputElement.prototype as HTMLInputElement & { showPicker?: () => void };
    const originalShowPicker = inputPrototype.showPicker;
    Object.defineProperty(inputPrototype, "showPicker", {
      configurable: true,
      value: showPicker,
    });

    try {
      render(<MonthControl month="2026-03" onMonthChange={vi.fn()} />);

      expect(screen.getByText("March 2026")).toBeInTheDocument();

      fireEvent.pointerDown(screen.getByTitle("Change month"));
      expect(screen.getByLabelText("Month")).toHaveFocus();
      expect(showPicker).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(inputPrototype, "showPicker", {
        configurable: true,
        value: originalShowPicker,
      });
    }
  });

  describe("off-month callout (#127)", () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date(2026, 10, 3, 12, 0, 0)); // November 2026
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows nothing for the current month", () => {
      render(<MonthControl month="2026-11" onMonthChange={vi.fn()} />);
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("shows a past-month callout that can't be dismissed, until the current month is back", () => {
      const { rerender } = render(<MonthControl month="2026-09" onMonthChange={vi.fn()} />);

      const callout = screen.getByRole("status");
      expect(callout).toHaveTextContent("Past month");
      expect(within(callout).queryByRole("button")).not.toBeInTheDocument();
      fireEvent.click(callout);
      fireEvent.keyDown(callout, { key: "Escape" });
      expect(screen.getByRole("status")).toHaveTextContent("Past month");

      rerender(<MonthControl month="2025-12" onMonthChange={vi.fn()} />);
      expect(screen.getByRole("status")).toHaveTextContent("Past month");

      rerender(<MonthControl month="2026-11" onMonthChange={vi.fn()} />);
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("says future month for a month ahead", () => {
      render(<MonthControl month="2026-12" onMonthChange={vi.fn()} />);
      expect(screen.getByRole("status")).toHaveTextContent("Future month");
    });
  });
});
