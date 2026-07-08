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
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;
  if (!Number.isFinite(year) || !Number.isFinite(monthIndex)) {
    return month;
  }
  const date = new Date(year, monthIndex, 1);
  return `${date.toLocaleString(undefined, { month: "short" })} '${String(year).slice(-2)}`;
}

export default function TrendBarChart({ points, ariaLabel }: TrendBarChartProps) {
  const maxAbs = Math.max(1, ...points.map((point) => Math.abs(point.value)));

  return (
    <div className="trendBarChart" role="img" aria-label={ariaLabel}>
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
