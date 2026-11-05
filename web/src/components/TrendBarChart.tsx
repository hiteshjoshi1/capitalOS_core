import * as fmt from "../lib/format";
import { useId } from "react";
import { describeSeries } from "../lib/chartA11y";
type TrendBarPoint = {
  /** "YYYY-MM" — formatted to "Mon 'YY" for display */
  month: string;
  value: number;
  displayValue: string;
  tone?: "positive" | "negative" | "neutral";
};

type TrendBarChartProps = {
  points: TrendBarPoint[];
  ariaLabel: string;
};

function formatTrendMonth(month: string): string {
  return fmt.formatMonth(month, "short");
}

export default function TrendBarChart({ points, ariaLabel }: TrendBarChartProps) {
  const descId = useId();
  const maxAbs = Math.max(1, ...points.map((point) => Math.abs(point.value)));

  return (
    <div className="trendBarChart" role="img" aria-label={ariaLabel} aria-describedby={descId}>
      <span id={descId} className="srOnly">
        {describeSeries(ariaLabel, points.map((p) => ({ label: formatTrendMonth(p.month), value: p.displayValue })))}
      </span>
      {points.map((point) => {
        const heightPct = Math.max(3, (Math.abs(point.value) / maxAbs) * 100);
        const tone = point.tone ?? (point.value < 0 ? "negative" : "neutral");
        return (
          <div className="trendBarColumn" key={point.month}>
            <span className="trendBarValue">{point.displayValue}</span>
            <div className="trendBarTrack">
              <span className={`trendBarFill ${tone}`} style={{ height: `${heightPct}%` }} />
            </div>
            <span className="trendBarMonth">{formatTrendMonth(point.month)}</span>
          </div>
        );
      })}
    </div>
  );
}
