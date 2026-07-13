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
  end: number;
};

function buildPieSlices(items: GeographyExposure["items"]): PieSlice[] {
  let offset = 0;
  return items.map((item, idx) => {
    const end = Math.min(100, offset + Math.max(0, item.percent));
    offset = end;
    return {
      item,
      idx,
      end,
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

function compactMappedTotal(total: number, currency: string | undefined): string {
  const prefix = currency === "SGD" ? "S$" : currency ?? "";
  const value = new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(total);
  return `${prefix} ${value}`.trim();
}

function formatAsOf(asOf: string | null | undefined): string {
  if (!asOf) return "Latest snapshot";
  const date = new Date(asOf);
  if (Number.isNaN(date.getTime())) return asOf;
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][date.getUTCMonth()];
  return `As of ${month} ${date.getUTCDate()}, ${date.getUTCFullYear()}`;
}

export default function GeographyPieCard({ exposure, formatMoney }: GeographyPieCardProps) {
  const items = exposure?.items ?? [];
  const total = exposure?.total ?? 0;
  const slices = buildPieSlices(items);
  const pieStyle = items.length > 0 ? { background: conicGradient(slices) } : undefined;

  return (
    <section className="card geographyPieCard">
      <div className="riskSectionHeader">
        <div>
          <div className="riskSectionEyebrow">Geography</div>
          <h2>Where the wealth is booked</h2>
        </div>
        <div className="muted stockHoldingsMeta">{items.length} markets</div>
      </div>

      {items.length === 0 ? (
        <div className="muted">No geographic exposure data yet.</div>
      ) : (
        <>
          <div className="geographyExposureLayout">
            <div className="geographyPieChartWrap">
              <div className="geographyPieChart" style={pieStyle} role="img" aria-label="Geographic exposure pie chart">
                <div className="geographyPieCenter">
                  <div className="label">Mapped</div>
                  <div className="val">{compactMappedTotal(total, exposure?.base_currency)}</div>
                </div>
              </div>
              <div className="muted geographyPieTotal">{formatAsOf(exposure?.as_of)}</div>
            </div>

            <div className="geographyLegendList">
              {items.map((item, idx) => {
                const breakdown = [
                  item.stocks_funds ? `Stocks ${formatMoney(item.stocks_funds)}` : null,
                  item.cash ? `Cash ${formatMoney(item.cash)}` : null,
                  item.crypto ? `Crypto ${formatMoney(item.crypto)}` : null,
                ].filter(Boolean);
                return (
                  <div className="geographyLegendRow" key={item.country}>
                    <div className="geographyLegendMain">
                      <span className="geographyLegendCountry">
                        <i style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}></i>
                        {item.country}
                      </span>
                      <span className="geographyLegendMeta">{breakdown.join(" · ") || "—"}</span>
                    </div>
                    <div className="geographyLegendValue">
                      <span>{formatMoney(item.total)}</span>
                      <strong>{item.percent.toFixed(1)}%</strong>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
