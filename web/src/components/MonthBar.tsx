import BaseCurrencyPicker from "./BaseCurrencyPicker";
import MonthControl from "./MonthControl";
import { formatMonth } from "../lib/format";
import { currentMonthYYYYMM, shiftMonth } from "../lib/selectedMonth";

type MonthBarProps = {
  month: string;
  onMonthChange: (month: string) => void;
};

/**
 * One month context per page (#264, #131 mock-up B): a bar under the page title with the
 * month (◂ picker ▸, "Live" for the current month, the "Past month" callout otherwise, and a
 * way back) and the base currency. It replaces the month + currency pills in the top bar's
 * header actions, which overflowed a phone (#239). Next stops at the current month.
 */
export default function MonthBar({ month, onMonthChange }: MonthBarProps) {
  const current = currentMonthYYYYMM();
  const previous = shiftMonth(month, -1);
  const next = shiftMonth(month, 1);
  const isCurrent = month === current;
  const canGoNext = month < current;

  const offMonthLabel = month < current ? "Past month" : month > current ? "Future month" : null;

  return (
    <div className="monthBar" role="group" aria-label="Month and currency">
      <div className="monthBarNav">
        <button
          type="button"
          className="monthBarStep"
          aria-label={`Previous month (${formatMonth(previous)})`}
          title={formatMonth(previous)}
          onClick={() => onMonthChange(previous)}
        >
          <span aria-hidden="true">◂</span>
        </button>
        <MonthControl month={month} onMonthChange={onMonthChange} hideOffMonth />
        <button
          type="button"
          className="monthBarStep"
          aria-label={`Next month (${formatMonth(next)})`}
          title={canGoNext ? formatMonth(next) : "This is the current month"}
          disabled={!canGoNext}
          onClick={() => onMonthChange(next)}
        >
          <span aria-hidden="true">▸</span>
        </button>
      </div>
      <div className="monthBarState">
        {isCurrent ? (
          <span className="monthBarLive">
            <span className="monthBarLiveDot" aria-hidden="true" />
            Live
          </span>
        ) : (
          <>
            {/* Same callout and wording as MonthControl's own (#127). */}
            <span className="monthControlOffMonth monthBarOffMonth" role="status">
              {offMonthLabel}
            </span>
            <button type="button" className="monthBarBack" onClick={() => onMonthChange(current)}>
              Back to {formatMonth(current, "medium")}
            </button>
          </>
        )}
      </div>
      <div className="monthBarCurrency">
        <BaseCurrencyPicker />
      </div>
    </div>
  );
}
