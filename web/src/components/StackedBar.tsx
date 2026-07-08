type StackedBarSegment = {
  key: string;
  label: string;
  percent: number;
  color: string;
  valueLabel?: string;
};

type StackedBarProps = {
  segments: StackedBarSegment[];
  ariaLabel: string;
};

export default function StackedBar({ segments, ariaLabel }: StackedBarProps) {
  return (
    <div>
      <div className="bar" title={ariaLabel}>
        {segments.map((segment) => (
          <span
            key={segment.key}
            style={{ width: `${Math.max(0, Math.min(100, segment.percent)).toFixed(1)}%`, background: segment.color }}
          />
        ))}
      </div>
      <div className="legend">
        {segments.map((segment) => (
          <span className="dot" key={segment.key}>
            <i style={{ background: segment.color }} />
            {segment.label} {segment.percent.toFixed(1)}%
            {segment.valueLabel ? ` · ${segment.valueLabel}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
