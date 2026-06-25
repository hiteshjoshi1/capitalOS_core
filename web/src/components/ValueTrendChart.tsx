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

  const width = 680;
  const height = 220;
  const left = 20;
  const right = 20;
  const top = 24;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const values = numericPoints.map((point) => point.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const padding = maxValue === minValue ? Math.max(maxValue * 0.08, 1) : (maxValue - minValue) * 0.12;
  const domainMin = Math.max(0, minValue - padding);
  const domainMax = maxValue + padding;
  const xFor = (index: number) =>
    left + ((numericPoints.length <= 1 ? 0.5 : index / (numericPoints.length - 1)) * plotWidth);
  const yFor = (value: number) => top + ((domainMax - value) / (domainMax - domainMin)) * plotHeight;
  const linePoints = numericPoints.map((point) => `${xFor(point.index).toFixed(1)},${yFor(point.value).toFixed(1)}`).join(" ");
  const yTicks = [domainMax, (domainMin + domainMax) / 2, domainMin];

  return (
    <div className="valueTrendChart" aria-label={ariaLabel}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-hidden="true">
        {yTicks.map((tick) => {
          const y = yFor(tick);
          return (
            <g key={tick.toFixed(2)}>
              <line className="valueTrendGridLine" x1={left} x2={width - right} y1={y} y2={y} />
            </g>
          );
        })}
        <line className="valueTrendAxisLine" x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} />
        <polyline className="valueTrendLine" points={linePoints} />
        {numericPoints.map((point) => (
          <text
            className="valueTrendMonthLabel"
            key={`label-${point.month}`}
            x={xFor(point.index)}
            y={height - 18}
            textAnchor="middle"
          >
            {formatTrendMonth(point.month)}
          </text>
        ))}
        {numericPoints.map((point) => {
          const x = xFor(point.index);
          const y = yFor(point.value);
          return (
            <g key={point.month}>
              <text className="valueTrendPointLabel" x={x} y={Math.max(14, y - 10)} textAnchor="middle">
                {formatCompactMoney(point.value)}
              </text>
              <circle className="valueTrendPoint" cx={x} cy={y} r="5">
                <title>{`${formatTrendMonth(point.month)}: ${formatMoney(point.value)}`}</title>
              </circle>
            </g>
          );
        })}
      </svg>
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
