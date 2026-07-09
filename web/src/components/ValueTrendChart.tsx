type ValueTrendPoint = {
  month: string;
  value?: number | null;
};

type ValueTrendChartProps = {
  points: ValueTrendPoint[];
  ariaLabel: string;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  formatCompactMoney: (value?: number | null) => string;
};

const formatTrendMonth = (month: string) => {
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;
  if (!Number.isFinite(year) || !Number.isFinite(monthIndex)) {
    return month;
  }
  const date = new Date(year, monthIndex, 1);
  return `${date.toLocaleString(undefined, { month: "short" })} '${String(year).slice(-2)}`;
};

export default function ValueTrendChart({
  points,
  ariaLabel,
  formatMoney,
  formatCompactMoney,
}: ValueTrendChartProps) {
  const numericPoints = points.reduce<Array<{ month: string; value: number; index: number }>>((acc, point) => {
    const value = point.value == null ? null : Number(point.value);
    if (value != null && Number.isFinite(value)) {
      acc.push({ month: point.month, value, index: acc.length });
    }
    return acc;
  }, []);

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
    <div className="valueTrendChart" aria-label={ariaLabel}>
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
                  className="valueTrendBar"
                  style={{ height: `${barHeightFor(point.value)}%` }}
                  title={`${formatTrendMonth(point.month)}: ${formatMoney(point.value)}`}
                />
              </div>
              <span className="valueTrendBarMonth">{formatTrendMonth(point.month)}</span>
            </div>
          );
        })}
      </div>
      <div className="valueTrendDataStrip">
        {numericPoints.map((point) => (
          <div className="valueTrendDataPoint" key={point.month}>
            <span>{formatTrendMonth(point.month)}</span>
            <strong>{formatMoney(point.value)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
