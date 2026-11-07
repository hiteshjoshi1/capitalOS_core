import { useRef } from "react";

import { currentMonthYYYYMM } from "../lib/selectedMonth";
import { formatMonth } from "../lib/format";

type MonthControlProps = {
  month: string;
  onMonthChange: (month: string) => void;
  /** The month bar (#264) shows the off-month state itself, after its ▸ step. */
  hideOffMonth?: boolean;
};

export default function MonthControl({ month, onMonthChange, hideOffMonth = false }: MonthControlProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const openMonthPicker = (): boolean => {
    const input = inputRef.current;
    if (!input) {
      return false;
    }
    input.focus({ preventScroll: true });
    try {
      if (typeof input.showPicker === "function") {
        input.showPicker();
        return true;
      }
    } catch {
      // Some browsers only allow showPicker during trusted user gestures.
    }
    return false;
  };

  // #127: while a month other than the current one is chosen, a small callout sits
  // next to the pill. It has no close button: it goes only when the current month
  // is chosen again.
  const currentMonth = currentMonthYYYYMM();
  const offMonthLabel = month < currentMonth ? "Past month" : month > currentMonth ? "Future month" : null;

  return (
    <span className="monthControl">
      <label
        className="coPillBtn"
        title="Change month"
        onPointerDown={(event) => {
          if (openMonthPicker()) {
            event.preventDefault();
          }
        }}
      >
        <span aria-hidden="true">{formatMonth(month)}</span>
        <input
          ref={inputRef}
          className="coPillBtnInput"
          aria-label="Month"
          type="month"
          value={month}
          onChange={(event) => onMonthChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openMonthPicker();
            }
          }}
        />
      </label>
      {offMonthLabel && !hideOffMonth && (
        <span className="monthControlOffMonth" role="status">
          {offMonthLabel}
        </span>
      )}
    </span>
  );
}
