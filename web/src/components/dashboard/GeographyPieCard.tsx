import type { GeographyExposure } from "../../lib/api";

type GeographyPieCardProps = {
  exposure: GeographyExposure | null;
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
};

const PIE_COLORS = [
  "#4f8cff",
  "#1fb981",
  "#f59f43",
  "#7d67ff",
  "#ef6ca8",
  "#2ebac6",
  "#f4cf5d",
  "#8f9db2",
];

type PieSlice = {
  item: GeographyExposure["items"][number];
  idx: number;
  start: number;
  end: number;
  mid: number;
};

function buildPieSlices(items: GeographyExposure["items"]): PieSlice[] {
  let offset = 0;
  return items.map((item, idx) => {
    const start = offset;
    const end = Math.min(100, start + Math.max(0, item.percent));
    offset = end;
    return {
      item,
      idx,
      start,
      end,
      mid: (start + end) / 2,
    };
  });
}

function conicGradient(slices: PieSlice[]): string {
  let offset = 0;
  const parts: string[] = [];
  slices.forEach((slice) => {
    const next = slice.end;
    parts.push(`${PIE_COLORS[slice.idx % PIE_COLORS.length]} ${offset.toFixed(2)}% ${next.toFixed(2)}%`);
    offset = next;
  });
  if (offset < 100) {
    parts.push(`color-mix(in srgb, var(--line) 65%, transparent 35%) ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

function sliceLabelPosition(midPercent: number): { left: string; top: string } {
  const angleDeg = (midPercent / 100) * 360 - 90;
  const radians = (angleDeg * Math.PI) / 180;
  const radius = 38;
  const x = 50 + radius * Math.cos(radians);
  const y = 50 + radius * Math.sin(radians);
  return { left: `${x.toFixed(2)}%`, top: `${y.toFixed(2)}%` };
}

export default function GeographyPieCard({ exposure, formatMoney }: GeographyPieCardProps) {
  const items = exposure?.items ?? [];
  const total = exposure?.total ?? 0;
  const slices = buildPieSlices(items);
  const overallPercent = items.reduce((sum, item) => sum + (Number.isFinite(item.percent) ? item.percent : 0), 0);
  const pieStyle = items.length > 0 ? { background: conicGradient(slices) } : undefined;

  return (
    <div className="card geographyPieCard">
      <div className="stockHoldingsHeader">
        <h2>Where the wealth is booked</h2>
        <div className="muted stockHoldingsMeta">{items.length} markets</div>
      </div>

      {items.length === 0 ? (
        <div className="muted">No geographic exposure data yet.</div>
      ) : (
        <>
          <div className="geographyPieChartWrap">
            <div className="geographyPieChart" style={pieStyle} aria-label="Geographic exposure pie chart">
              {slices
                .filter((slice) => slice.end > slice.start)
                .map((slice) => (
                  <span
                    key={`slice-label-${slice.item.country}-${slice.idx}`}
                    className="geographyPieSliceLabel"
                    style={sliceLabelPosition(slice.mid)}
                  >
                    {slice.item.percent.toFixed(1)}%
                  </span>
                ))}
              <div className="geographyPieCenter">
                <div className="label">Geo</div>
                <div className="val">{overallPercent.toFixed(1)}%</div>
              </div>
            </div>
            <div className="muted geographyPieTotal">Overall mapped: {formatMoney(total)}</div>
          </div>

          <div className="listRows">
            {items.map((item, idx) => {
              const breakdown = [
                item.stocks_funds ? `Stocks ${formatMoney(item.stocks_funds)}` : null,
                item.cash ? `Cash ${formatMoney(item.cash)}` : null,
                item.crypto ? `Crypto ${formatMoney(item.crypto)}` : null,
              ].filter(Boolean);
              return (
                <div className="listRow" key={item.country}>
                  <div className="listRowMain">
                    <span className="listRowTitle">
                      <span className="geographyLegendCountry">
                        <i style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}></i>
                        {item.country}
                      </span>
                    </span>
                    <span className="listRowMeta">{breakdown.join(" · ") || "—"}</span>
                  </div>
                  <div className="listRowValue">
                    {item.percent.toFixed(1)}%
                    <span className="listRowValueSecondary muted">{formatMoney(item.total)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
