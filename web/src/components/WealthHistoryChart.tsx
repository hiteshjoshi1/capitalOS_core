import { useMemo, useRef, useState } from "react";
import type { WealthTimeline, WealthTimelinePoint } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { computeMonthFlags, isCarriedPoint, isGapPoint } from "../lib/wealthHistoryAnalysis";

export type WealthHistoryChartMode = "total" | "comp";

type SeriesKey = "total" | "stocks_funds" | "cash" | "crypto";

type SeriesDef = {
  key: SeriesKey;
  color: string;
  name: string;
};

const COMPONENT_LABEL: Record<string, string> = {
  stocks_funds: "Stocks & funds",
  cash: "Cash",
  crypto: "Crypto",
};

type Props = {
  points: WealthTimelinePoint[];
  now: WealthTimeline["now"];
  mode: WealthHistoryChartMode;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  formatMoneyShort: (value?: number | null) => string;
  onSelectMonth?: (month: string) => void;
};

const M = { l: 60, r: 24, t: 20, b: 30 };
const W = 900;
const H = 320;

function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  const year = Number(y);
  const mon = Number(m);
  if (!Number.isFinite(year) || !Number.isFinite(mon)) return month;
  return new Date(year, mon - 1, 1).toLocaleString("en", { month: "short", year: "2-digit" });
}

function niceStep(range: number): number {
  if (range <= 0) return 1;
  const rough = range / 5;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const normalized = rough / magnitude;
  const step = normalized >= 5 ? 5 : normalized >= 2 ? 2 : 1;
  return step * magnitude;
}

export default function WealthHistoryChart({ points, now, mode, formatMoney, formatMoneyShort, onSelectMonth }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const n = points.length;
  const seriesDefs: SeriesDef[] = useMemo(
    () =>
      mode === "total"
        ? [{ key: "total", color: "var(--wh-total)", name: "Total" }]
        : [
            { key: "stocks_funds", color: "var(--wh-stocks)", name: "Stocks & funds" },
            { key: "cash", color: "var(--wh-cash)", name: "Cash" },
            { key: "crypto", color: "var(--wh-crypto)", name: "Crypto" },
          ],
    [mode],
  );

  const innerW = W - M.l - M.r;
  const innerH = H - M.t - M.b;
  // n month slots + 1 reserved for the "now" marker, evenly spaced.
  const step = n > 0 ? innerW / (n + 1) : innerW;
  const xAt = (i: number) => M.l + step * (i + 0.5);
  const xNow = xAt(n);

  const monthFlags = useMemo(() => computeMonthFlags(points), [points]);

  const { lo, hi } = useMemo(() => {
    const vals: number[] = [];
    for (const p of points) {
      if (isGapPoint(p)) continue;
      for (const s of seriesDefs) vals.push(p[s.key] as number);
    }
    for (const s of seriesDefs) vals.push(now[s.key] as number);
    if (vals.length === 0) return { lo: 0, hi: 1 };
    let min = Math.min(...vals, mode === "comp" ? 0 : Math.min(...vals));
    let max = Math.max(...vals);
    if (mode === "comp") min = Math.min(0, min);
    const pad = (max - min) * 0.1 || Math.abs(max) * 0.1 || 1;
    return { lo: min - (mode === "comp" ? 0 : pad), hi: max + pad };
  }, [points, now, seriesDefs, mode]);

  const y = (v: number) => M.t + innerH - ((v - lo) / (hi - lo || 1)) * innerH;

  const gridStep = niceStep(hi - lo);
  const gridLines: number[] = [];
  for (let v = Math.ceil(lo / gridStep) * gridStep; v <= hi; v += gridStep) gridLines.push(v);

  const xLabelEvery = n <= 8 ? 1 : n <= 16 ? 2 : Math.ceil(n / 8);

  const handlePointerMove = (evt: React.PointerEvent<HTMLDivElement>) => {
    const svg = svgRef.current;
    if (!svg || n === 0) return;
    const rect = svg.getBoundingClientRect();
    const px = ((evt.clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i <= n; i++) {
      const d = Math.abs((i === n ? xNow : xAt(i)) - px);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    setHoverIdx(best);
  };

  const hoverPoint = hoverIdx != null && hoverIdx < n ? points[hoverIdx] : null;
  const isHoverNow = hoverIdx === n;

  return (
    <div className="whChartWrap">
      <div
        className="whChartSvgHost"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIdx(null)}
        onClick={() => {
          if (hoverPoint && onSelectMonth) onSelectMonth(hoverPoint.month);
        }}
      >
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Net worth over time">
          {gridLines.map((v) => (
            <g key={v}>
              <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className="whGridLine" />
              <text x={M.l - 8} y={y(v) + 4} textAnchor="end" className="whAxisLabel">
                {formatMoneyShort(v)}
              </text>
            </g>
          ))}

          {points.map((p, i) =>
            i % xLabelEvery === 0 ? (
              <text key={p.month} x={xAt(i)} y={H - 8} textAnchor="middle" className="whAxisLabel">
                {monthLabel(p.month)}
              </text>
            ) : null,
          )}
          <text x={xNow} y={H - 8} textAnchor="middle" className="whAxisLabel whAxisLabelNow">
            now
          </text>

          {points.map((p) =>
            p.uploads.length > 0 ? (
              <rect
                key={`upload-${p.month}`}
                x={xAt(points.indexOf(p)) - 4}
                y={M.t + innerH + 5}
                width={8}
                height={8}
                transform={`rotate(45 ${xAt(points.indexOf(p))} ${M.t + innerH + 9})`}
                className="whUploadMark"
              >
                <title>{`Upload: ${p.uploads.map(formatPlatformLabel).join(", ")}`}</title>
              </rect>
            ) : null,
          )}

          {seriesDefs.map((s) => (
            <g key={s.key}>
              {points.slice(1).map((p, idx) => {
                const i = idx + 1;
                const prev = points[i - 1];
                if (isGapPoint(prev) || isGapPoint(p)) return null;
                const carried = isCarriedPoint(prev) || isCarriedPoint(p);
                return (
                  <line
                    key={`${s.key}-seg-${i}`}
                    x1={xAt(i - 1)}
                    y1={y(prev[s.key] as number)}
                    x2={xAt(i)}
                    y2={y(p[s.key] as number)}
                    stroke={s.color}
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeDasharray={carried ? "5 5" : undefined}
                    opacity={carried ? 0.6 : 1}
                  />
                );
              })}
              {n > 0 && !isGapPoint(points[n - 1]) ? (
                <line
                  x1={xAt(n - 1)}
                  y1={y(points[n - 1][s.key] as number)}
                  x2={xNow}
                  y2={y(now[s.key] as number)}
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray="2 4"
                  opacity={0.7}
                />
              ) : null}

              {points.map((p, i) => {
                if (isGapPoint(p)) return null;
                const carried = isCarriedPoint(p);
                const v = y(p[s.key] as number);
                return (
                  <g key={`${s.key}-dot-${p.month}`}>
                    <circle cx={xAt(i)} cy={v} r={6} className="whDotRing" />
                    <circle
                      cx={xAt(i)}
                      cy={v}
                      r={4}
                      fill={carried ? "transparent" : s.color}
                      stroke={s.color}
                      strokeWidth={2}
                    />
                  </g>
                );
              })}
              <circle cx={xNow} cy={y(now[s.key] as number)} r={5} className="whNowDot" stroke={s.color} />
            </g>
          ))}

          {mode === "total"
            ? points.map((p, i) => {
                if (isGapPoint(p)) return null;
                const f = monthFlags.get(p.month);
                if (!f?.isOutlier) return null;
                const cy = y(p.total) - 18;
                return (
                  <g
                    key={`outlier-${p.month}`}
                    className="whOutlierBadge"
                    onClick={() => onSelectMonth?.(p.month)}
                  >
                    <circle cx={xAt(i)} cy={cy} r={9} />
                    <text x={xAt(i)} y={cy + 4} textAnchor="middle">
                      !
                    </text>
                    <title>
                      {`${p.month}: ${f.delta != null && f.delta < 0 ? "down" : "up"} sharply` +
                        (f.dominantComponent ? ` — driven by ${COMPONENT_LABEL[f.dominantComponent]}` : "")}
                    </title>
                  </g>
                );
              })
            : null}

          {hoverIdx != null ? (
            <line
              x1={isHoverNow ? xNow : xAt(hoverIdx)}
              x2={isHoverNow ? xNow : xAt(hoverIdx)}
              y1={M.t}
              y2={M.t + innerH}
              className="whCrosshair"
            />
          ) : null}
        </svg>

        {hoverIdx != null ? (
          <div
            className="whTooltip"
            style={{ left: `${Math.min(((isHoverNow ? xNow : xAt(hoverIdx)) / W) * 100, 68).toFixed(2)}%` }}
          >
            {isHoverNow ? (
              <>
                <div className="whTooltipTitle">Now (live prices)</div>
                <div className="whTooltipRow">
                  <span>Total</span>
                  <strong>{formatMoney(now.total)}</strong>
                </div>
              </>
            ) : hoverPoint ? (
              <>
                <div className="whTooltipTitle">
                  {monthLabel(hoverPoint.month)}
                  {isGapPoint(hoverPoint)
                    ? " · no data"
                    : isCarriedPoint(hoverPoint)
                      ? " · partially carried"
                      : " · observed"}
                </div>
                {isGapPoint(hoverPoint) ? (
                  <div className="whTooltipRow">
                    <span>No sources reported for this month</span>
                  </div>
                ) : (
                  <>
                    <div className="whTooltipRow">
                      <span>Total</span>
                      <strong>{formatMoney(hoverPoint.total)}</strong>
                    </div>
                    <div className="whTooltipRow">
                      <span>Stocks & funds</span>
                      <strong>{formatMoney(hoverPoint.stocks_funds)}</strong>
                    </div>
                    <div className="whTooltipRow">
                      <span>Cash</span>
                      <strong>{formatMoney(hoverPoint.cash)}</strong>
                    </div>
                    <div className="whTooltipRow">
                      <span>Crypto</span>
                      <strong>{formatMoney(hoverPoint.crypto)}</strong>
                    </div>
                    {hoverPoint.liabilities > 0 ? (
                      <div className="whTooltipRow">
                        <span>Liabilities</span>
                        <strong>-{formatMoney(hoverPoint.liabilities)}</strong>
                      </div>
                    ) : null}
                    {hoverPoint.source_freshness
                      .filter((s) => s.status !== "fresh")
                      .map((s) => (
                        <div className="whTooltipCarriedNote" key={s.platform}>
                          ⚠ {formatPlatformLabel(s.platform)} as of {s.as_of ?? "—"}
                          {s.days_old != null ? ` (${s.days_old}d old)` : ""}
                        </div>
                      ))}
                    {hoverPoint.uploads.length > 0 ? (
                      <div className="whTooltipUploadNote">
                        Uploaded: {hoverPoint.uploads.map(formatPlatformLabel).join(", ")}
                      </div>
                    ) : null}
                    {monthFlags.get(hoverPoint.month)?.isCatchUp ? (
                      <div className="whTooltipCarriedNote">
                        ⚠ Catch-up month — includes drift accrued since the last upload
                      </div>
                    ) : null}
                    {onSelectMonth ? <div className="whTooltipHint">Click to inspect this month →</div> : null}
                  </>
                )}
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="whLegendRow">
        {mode === "comp" ? (
          <div className="whSeriesLegend">
            {seriesDefs.map((s) => (
              <span key={s.key} className="whSeriesLegendItem">
                <span className="whSeriesLegendKey" style={{ borderColor: s.color }} />
                {s.name}
              </span>
            ))}
          </div>
        ) : null}
        <div className="whHonestyLegend">
          <span className="whHonestyItem">
            <span className="whHonestyDot whHonestyDotFresh" /> observed
          </span>
          <span className="whHonestyItem">
            <span className="whHonestyDot whHonestyDotCarried" /> carried (stale source)
          </span>
          <span className="whHonestyItem">
            <span className="whHonestyDiamond" /> upload landed
          </span>
          <span className="whHonestyItem">
            <span className="whHonestyDot whHonestyDotNow" /> now (live)
          </span>
          {mode === "total" ? (
            <span className="whHonestyItem">
              <span className="whHonestyOutlierMark">!</span> unusual move
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
