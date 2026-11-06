import { useId } from "react";
import * as fmt from "../lib/format";
import { describeSeries } from "../lib/chartA11y";
type ValueTrendPoint = {
  month: string;
  value?: number | null;
  /** #241 (D-61): the open month's bar, live and month to date: labelled "MTD", hatched. */
  is_live?: boolean;
};

type ValueTrendChartProps = {
  points: ValueTrendPoint[];
  ariaLabel: string;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  formatCompactMoney: (value?: number | null) => string;
};

const formatTrendMonth = (month: string) => fmt.formatMonth(month, "short");
/** The bar's name for screen readers and its tooltip. */
const describeTrendMonth = (point: { month: string; isLive: boolean }) =>
  point.isLive ? `${formatTrendMonth(point.month)} (month to date, live)` : formatTrendMonth(point.month);
/** The visible label under a bar and in the data strip. */
const trendMonthLabel = (point: { month: string; isLive: boolean }) => (point.isLive ? "MTD" : formatTrendMonth(point.month));

export default function ValueTrendChart({
  points,
  ariaLabel,
  formatMoney,
  formatCompactMoney,
}: ValueTrendChartProps) {
  const descId = useId();
  const numericPoints = points.reduce<Array<{ month: string; value: number; index: number; isLive: boolean }>>(
    (acc, point) => {
      const value = point.value == null ? null : Number(point.value);
      if (value != null && Number.isFinite(value)) {
        acc.push({ month: point.month, value, index: acc.length, isLive: point.is_live === true });
      }
      return acc;
    },
    [],
  );

  if (numericPoints.length === 0) {
    return <div className="muted valueTrendEmpty">Not enough history yet.</div>;
  }

  const values = numericPoints.map((point) => point.value);
  const maxValue = Math.max(...values);
  const barHeightFor = (value: number) => {
    if (maxValue <= 0) {
      return 8;
    }
    return Math.max(8, Math.round((value / maxValue) * 100));
  };

  return (
    <div className="valueTrendChart" role="img" aria-label={ariaLabel} aria-describedby={descId}>
      <span id={descId} className="srOnly">
        {describeSeries(
          ariaLabel,
          numericPoints.map((p) => ({ label: describeTrendMonth(p), value: formatMoney(p.value) })),
        )}
      </span>
      <div
        className="valueTrendBars"
        style={{ gridTemplateColumns: `repeat(${numericPoints.length}, minmax(0, 1fr))` }}
        role="img"
        aria-hidden="true"
      >
        {numericPoints.map((point) => {
          return (
            <div className="valueTrendBarItem" key={point.month}>
              <span className="valueTrendBarValue">{formatCompactMoney(point.value)}</span>
              <div className="valueTrendBarTrack">
                <div
                  className={`valueTrendBar${point.isLive ? " live" : ""}`}
                  style={{ height: `${barHeightFor(point.value)}%` }}
                  title={`${describeTrendMonth(point)}: ${formatMoney(point.value)}`}
                />
              </div>
              <span className="valueTrendBarMonth">{trendMonthLabel(point)}</span>
            </div>
          );
        })}
      </div>
      <div className="valueTrendDataStrip">
        {numericPoints.map((point) => (
          <div className="valueTrendDataPoint" key={point.month}>
            <span>{trendMonthLabel(point)}</span>
            <strong>{formatMoney(point.value)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
