import type { ReactNode } from "react";

type StackedBarSegment = {
  key: string;
  label: string;
  /** Share of the bar width, 0-100. */
  percent: number;
  color: string;
  /** Custom right-aligned (rows layout) or trailing (wrap layout) content. */
  valueLabel?: ReactNode;
};

type StackedBarProps = {
  segments: StackedBarSegment[];
  ariaLabel: string;
  /** "rows" = one full-width space-between row per segment (value + share).
   *  "wrap" = compact horizontal wrapping legend, good for 2-3 segments. */
  layout?: "rows" | "wrap";
};

export default function StackedBar({ segments, ariaLabel, layout = "wrap" }: StackedBarProps) {
  return (
    <div>
      <div className="bar stackedBarTrack" title={ariaLabel}>
        {segments.map((segment) => (
          <span
            key={segment.key}
            style={{ width: `${Math.max(0, Math.min(100, segment.percent)).toFixed(1)}%`, background: segment.color }}
          />
        ))}
      </div>
      {layout === "rows" ? (
        <div className="cashFlowLegendList">
          {segments.map((segment) => (
            <div className="cashFlowLegendRow" key={segment.key}>
              <span className="cashFlowLegendLabel">
                <i style={{ background: segment.color }} />
                <span className="cashFlowLegendText">{segment.label}</span>
              </span>
              <span className="muted">{segment.valueLabel}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="legend">
          {segments.map((segment) => (
            <span className="dot" key={segment.key}>
              <i style={{ background: segment.color }} />
              {segment.label}
              {segment.valueLabel ? <> — {segment.valueLabel}</> : null}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
