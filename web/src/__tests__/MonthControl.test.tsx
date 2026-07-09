import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
});
