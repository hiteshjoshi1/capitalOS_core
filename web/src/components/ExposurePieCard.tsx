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

type ExposurePieItem = {
  label: string;
  value: number;
  percent: number;
};

type ExposurePieCardProps = {
  title: string;
  subtitle: string;
  items: ExposurePieItem[];
  totalLabel: string;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  ariaLabel: string;
  className?: string;
};

function conicGradient(items: ExposurePieItem[]) {
  let offset = 0;
  const parts = items.map((item, idx) => {
    const next = offset + Math.max(0, item.percent);
    const part = `${PIE_COLORS[idx % PIE_COLORS.length]} ${offset.toFixed(2)}% ${next.toFixed(2)}%`;
    offset = next;
    return part;
  });
  if (offset < 100) {
    parts.push(`color-mix(in srgb, var(--line) 65%, transparent 35%) ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

export default function ExposurePieCard({
  title,
  subtitle,
  items,
  totalLabel,
  formatMoney,
  ariaLabel,
  className,
}: ExposurePieCardProps) {
  const pieStyle = items.length > 0 ? { background: conicGradient(items) } : undefined;

  return (
    <div className={["card", className].filter(Boolean).join(" ")}>
      <div className="stockHoldingsHeader">
        <h2>{title}</h2>
        <div className="muted stockHoldingsMeta">{subtitle}</div>
      </div>
      {items.length === 0 ? (
        <div className="muted">No exposure data yet.</div>
      ) : (
        <>
          <div className="cashFlowDonutLayout">
            <div className="cashFlowDonutChart" style={pieStyle} aria-label={ariaLabel}>
              <div className="cashFlowDonutCenter">
                <span className="label">Total</span>
                <strong>{totalLabel}</strong>
              </div>
            </div>
            <div className="cashFlowLegendList">
              {items.map((item, idx) => (
                <div key={item.label} className="cashFlowLegendRow">
                  <span className="cashFlowLegendLabel">
                    <i style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}></i>
                    <span className="cashFlowLegendText">{item.label}</span>
                  </span>
                  <span>{item.percent.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Segment</th>
                <th className="right">Value</th>
                <th className="right">Share</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`row-${item.label}`}>
                  <td>{item.label}</td>
                  <td className="right">{formatMoney(item.value)}</td>
                  <td className="right">{item.percent.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
