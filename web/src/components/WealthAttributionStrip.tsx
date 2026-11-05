import { useMemo, useState } from "react";
import type { WealthTimelinePoint } from "../lib/api";
import { computeMonthFlags, isGapPoint } from "../lib/wealthHistoryAnalysis";
import * as fmt from "../lib/format";

type Props = {
  points: WealthTimelinePoint[];
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  selectedMonth: string | null;
  onSelectMonth?: (month: string) => void;
};

// Must match WealthHistoryChart's geometry so the two charts' x-axes align.
const M = { l: 60, r: 24 };
const W = 900;
const H = 110;
const T = 6;
const B = 4;

const COMPONENT_ORDER = ["stocks_funds", "cash", "crypto"] as const;
const COMPONENT_COLOR: Record<(typeof COMPONENT_ORDER)[number], string> = {
  stocks_funds: "var(--wh-stocks)",
  cash: "var(--wh-cash)",
  crypto: "var(--wh-crypto)",
};

function monthLabel(month: string): string {
  return fmt.formatMonth(month, "short");
}

export default function WealthAttributionStrip({ points, formatMoney, selectedMonth, onSelectMonth }: Props) {
  const [hoverMonth, setHoverMonth] = useState<string | null>(null);
  const n = points.length;
  const step = n > 0 ? (W - M.l - M.r) / (n + 1) : W - M.l - M.r;
  const xAt = (i: number) => M.l + step * (i + 0.5);

  const monthFlags = useMemo(() => computeMonthFlags(points), [points]);

  const innerH = H - T - B;
  const zero = T + innerH / 2;

  const maxAbs = useMemo(() => {
    let max = 1;
    for (const p of points) {
      const f = monthFlags.get(p.month);
      if (!f?.componentDeltas) continue;
      const up = COMPONENT_ORDER.reduce((sum, k) => sum + Math.max(0, f.componentDeltas![k]), 0);
      const down = COMPONENT_ORDER.reduce((sum, k) => sum + Math.max(0, -f.componentDeltas![k]), 0);
      max = Math.max(max, up, down);
    }
    return max;
  }, [points, monthFlags]);

  const scale = (innerH / 2 - 2) / maxAbs;
  const barWidth = Math.min(16, step * 0.5);

  // #151: keyboard drill-down, as on the chart above: arrows move between the months
  // that have a column, Enter or Space inspects one, Escape lets go.
  const columnMonths = points.filter((p) => !isGapPoint(p) && monthFlags.get(p.month)?.componentDeltas).map((p) => p.month);
  const handleKeyDown = (evt: React.KeyboardEvent<HTMLDivElement>) => {
    if (columnMonths.length === 0) return;
    const current = hoverMonth ? columnMonths.indexOf(hoverMonth) : -1;
    let next: number | null = null;
    if (evt.key === "ArrowRight") next = Math.min(columnMonths.length - 1, current + 1);
    else if (evt.key === "ArrowLeft") next = current < 0 ? columnMonths.length - 1 : Math.max(0, current - 1);
    else if (evt.key === "Home") next = 0;
    else if (evt.key === "End") next = columnMonths.length - 1;
    else if (evt.key === "Escape") {
      setHoverMonth(null);
      return;
    } else if (evt.key === "Enter" || evt.key === " ") {
      evt.preventDefault();
      if (hoverMonth) onSelectMonth?.(hoverMonth);
      return;
    }
    if (next != null) {
      evt.preventDefault();
      setHoverMonth(columnMonths[next]);
    }
  };

  const hoverPoint = hoverMonth ? points.find((p) => p.month === hoverMonth) : null;
  const hoverFlags = hoverMonth ? monthFlags.get(hoverMonth) : null;
  const hoverIdx = hoverMonth ? points.findIndex((p) => p.month === hoverMonth) : -1;

  return (
    <div className="whAttribWrap">
      <div className="whAttribHead">
        <span className="whCardTitle" style={{ fontSize: "13.5px" }}>
          What moved it — month-over-month, by component
        </span>
        <span className="whCardMeta">Click a column (or a point above), or use the arrow keys and Enter, to inspect that month.</span>
      </div>
      <div
        className="whChartSvgHost"
        tabIndex={columnMonths.length > 0 ? 0 : undefined}
        role="group"
        aria-label="Month-over-month change by component. Use the arrow keys to move between months and Enter to inspect one."
        onPointerLeave={() => setHoverMonth(null)}
        onFocus={() => {
          if (!hoverMonth && columnMonths.length > 0) setHoverMonth(columnMonths[columnMonths.length - 1]);
        }}
        onBlur={() => setHoverMonth(null)}
        onKeyDown={handleKeyDown}
      >
        <span className="srOnly" aria-live="polite">
          {hoverPoint && hoverFlags?.componentDeltas
            ? `${fmt.formatMonth(hoverPoint.month)}: stocks and funds ${formatMoney(hoverFlags.componentDeltas.stocks_funds)}, cash ${formatMoney(hoverFlags.componentDeltas.cash)}, crypto ${formatMoney(hoverFlags.componentDeltas.crypto)}`
            : ""}
        </span>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Month-over-month change by component">
          <line x1={M.l} x2={W - M.r} y1={zero} y2={zero} className="whGridLine" />
          {points.map((p, i) => {
            if (isGapPoint(p)) return null;
            const f = monthFlags.get(p.month);
            if (!f?.componentDeltas) return null;
            const x = xAt(i) - barWidth / 2;
            let up = zero;
            let down = zero;
            const segments = COMPONENT_ORDER.map((key) => {
              const v = f.componentDeltas![key];
              if (!v) return null;
              const h = Math.max(1, Math.abs(v) * scale);
              let segY: number;
              if (v > 0) {
                segY = up - h;
                up = segY - 2;
              } else {
                segY = down + 2;
                down = segY + h;
              }
              return { key, y: segY, h };
            });
            const isSelected = p.month === selectedMonth;
            return (
              <g
                key={p.month}
                className={`whAttribCol${isSelected ? " whAttribColSelected" : ""}`}
                onPointerEnter={() => setHoverMonth(p.month)}
                onClick={() => onSelectMonth?.(p.month)}
              >
                <rect x={x - 3} y={T} width={barWidth + 6} height={innerH} className="whAttribHitArea" />
                {segments.map((seg) =>
                  seg ? (
                    <rect
                      key={seg.key}
                      x={x}
                      y={seg.y}
                      width={barWidth}
                      height={seg.h}
                      rx={2}
                      fill={COMPONENT_COLOR[seg.key]}
                      opacity={f.isCatchUp ? 0.5 : 1}
                    />
                  ) : null,
                )}
              </g>
            );
          })}
        </svg>

        {hoverPoint && hoverFlags?.componentDeltas ? (
          <div
            className="whTooltip"
            style={{ left: `${Math.min((xAt(hoverIdx) / W) * 100, 68).toFixed(2)}%`, top: 0 }}
          >
            <div className="whTooltipTitle">
              {monthLabel(hoverPoint.month)} Δ
              {hoverFlags.comparedToMonth ? ` vs ${monthLabel(hoverFlags.comparedToMonth)}` : ""}
            </div>
            <div className="whTooltipRow">
              <span>Stocks & funds</span>
              <strong>{formatMoney(hoverFlags.componentDeltas.stocks_funds)}</strong>
            </div>
            <div className="whTooltipRow">
              <span>Cash</span>
              <strong>{formatMoney(hoverFlags.componentDeltas.cash)}</strong>
            </div>
            <div className="whTooltipRow">
              <span>Crypto</span>
              <strong>{formatMoney(hoverFlags.componentDeltas.crypto)}</strong>
            </div>
            {hoverFlags.isCatchUp ? (
              <div className="whTooltipCarriedNote">⚠ Catch-up month — includes multi-month drift</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
