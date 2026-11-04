import type { GeographyExposure } from "../../lib/api";
import * as fmt from "../../lib/format";
import { chartColor } from "../../lib/chartColors";

type GeographyPieCardProps = {
  exposure: GeographyExposure | null;
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
};


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
    parts.push(`${chartColor(slice.idx)} ${offset.toFixed(2)}% ${next.toFixed(2)}%`);
    offset = next;
  });
  if (offset < 100) {
    parts.push(`color-mix(in srgb, var(--line) 65%, transparent 35%) ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

function compactMappedTotal(total: number, currency: string | undefined): string {
  return fmt.formatMoneyCompact(total, currency);
}

function formatAsOf(asOf: string | null | undefined): string {
  if (!asOf) return "Latest snapshot";
  const label = fmt.formatDate(asOf);
  return label === fmt.MISSING ? asOf : `As of ${label}`;
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
                        <i style={{ background: chartColor(idx) }}></i>
                        {item.country}
                      </span>
                      <span className="geographyLegendMeta">{breakdown.join(" · ") || "—"}</span>
                    </div>
                    <div className="geographyLegendValue">
                      <span>{formatMoney(item.total)}</span>
                      <strong>{fmt.formatPercent(item.percent, { scale: "points" })}</strong>
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
