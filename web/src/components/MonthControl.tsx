import { useRef } from "react";

type MonthControlProps = {
  month: string;
  onMonthChange: (month: string) => void;
};

function formatMonthLabel(month: string): string {
  const [yearStr, monStr] = month.split("-");
  const year = Number(yearStr);
  const mon = Number(monStr);
  if (!Number.isFinite(year) || !Number.isFinite(mon)) return month;
  return new Date(year, mon - 1, 1).toLocaleString("en", {
    month: "long",
    year: "numeric",
  });
}

export default function MonthControl({ month, onMonthChange }: MonthControlProps) {
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

  return (
    <label
      className="coPillBtn"
      title="Change month"
      onPointerDown={(event) => {
        if (openMonthPicker()) {
          event.preventDefault();
        }
      }}
    >
      <span aria-hidden="true">{formatMonthLabel(month)}</span>
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
  );
}
