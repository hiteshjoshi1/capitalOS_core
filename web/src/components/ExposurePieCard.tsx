import * as fmt from "../lib/format";
import { chartColor, donutGradient } from "../lib/chartColors";
import { useId } from "react";
import { describeShares } from "../lib/chartA11y";

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
  return donutGradient(items.map((item) => item.percent));
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
  const descId = useId();
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
            <div className="cashFlowDonutChart" style={pieStyle} role="img" aria-label={ariaLabel} aria-describedby={descId}>
              <span id={descId} className="srOnly">{describeShares(ariaLabel, items)}</span>
              <div className="cashFlowDonutCenter">
                <span className="label">Total</span>
                <strong>{totalLabel}</strong>
              </div>
            </div>
            <div className="cashFlowLegendList">
              {items.map((item, idx) => (
                <div key={item.label} className="cashFlowLegendRow">
                  <span className="cashFlowLegendLabel">
                    <i style={{ background: chartColor(idx) }}></i>
                    <span className="cashFlowLegendText">{item.label}</span>
                  </span>
                  <span>{fmt.formatPercent(item.percent, { scale: "points" })}</span>
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
                  <td className="right">{fmt.formatPercent(item.percent, { scale: "points" })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
