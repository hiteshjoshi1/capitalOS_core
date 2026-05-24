type MiniTrendPoint = {
  month: string;
  value?: number | null;
};

type MiniTrendProps = {
  points: MiniTrendPoint[];
  ariaLabel: string;
};

export default function MiniTrend({ points, ariaLabel }: MiniTrendProps) {
  const numericPoints = points
    .map((point, index) => ({ ...point, index, value: point.value == null ? null : Number(point.value) }))
    .filter((point): point is MiniTrendPoint & { index: number; value: number } => point.value != null && Number.isFinite(point.value));

  if (numericPoints.length === 0) {
    return <div className="muted">Not enough history yet.</div>;
  }

  const values = numericPoints.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = 240;
  const height = 80;
  const xStep = numericPoints.length === 1 ? width / 2 : width / (numericPoints.length - 1);
  const yFor = (value: number) => {
    if (max === min) {
      return height / 2;
    }
    return height - (((value - min) / (max - min)) * (height - 12) + 6);
  };
  const pointsString = numericPoints
    .map((point, index) => `${(index * xStep).toFixed(1)},${yFor(point.value).toFixed(1)}`)
    .join(" ");

  return (
    <div aria-label={ariaLabel}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-hidden="true" style={{ width: "100%", maxWidth: 280 }}>
        <polyline
          fill="none"
          stroke="var(--accent)"
          strokeWidth="3"
          strokeLinejoin="round"
          strokeLinecap="round"
          points={pointsString}
        />
        {numericPoints.map((point, index) => (
          <circle
            key={`${point.month}-${point.index}`}
            cx={index * xStep}
            cy={yFor(point.value)}
            r="3"
            fill="var(--accent)"
          />
        ))}
      </svg>
      <div className="muted" style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12 }}>
        <span>{points[0]?.month ?? "—"}</span>
        <span>{points[points.length - 1]?.month ?? "—"}</span>
      </div>
    </div>
  );
}
