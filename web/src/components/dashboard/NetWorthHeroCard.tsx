import type { DashboardSummary } from "../../lib/api";
import { Link } from "react-router-dom";

type NetWorthHeroCardProps = {
  summary: DashboardSummary | null;
  cashPct: number;
  stocksPct: number;
  cryptoPct: number;
  cashFlowNet?: number;
  cashFlowMonth?: string;
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
};

export default function NetWorthHeroCard({
  summary,
  cashPct,
  stocksPct,
  cryptoPct,
  cashFlowNet,
  cashFlowMonth,
  formatMoney,
}: NetWorthHeroCardProps) {
  const prevMonthChange = summary?.net_worth_change?.vs_prev_month;
  const prevYearChange = summary?.net_worth_change?.vs_prev_year;

  const formatDelta = (abs: number, pct: number | null) => {
    const sign = abs >= 0 ? "+" : "-";
    const percentValue = pct == null ? "" : ` (${pct >= 0 ? "+" : "-"}${Math.abs(pct * 100).toFixed(1)}%)`;
    return `${sign}${formatMoney(Math.abs(abs))}${percentValue}`;
  };

  return (
    <div className="card netWorthCard">
      <h2>Net Worth</h2>
      <div className="big">{formatMoney(summary?.net_worth.total)}</div>
      {prevMonthChange || prevYearChange ? (
        <div className="netWorthDeltaRow" aria-label="Net worth changes">
          {prevMonthChange ? (
            <div className="netWorthDelta">
              <span className="label">vs {prevMonthChange.compare_month}</span>
              <span className={prevMonthChange.abs >= 0 ? "good" : "bad"}>
                {formatDelta(prevMonthChange.abs, prevMonthChange.pct)}
              </span>
            </div>
          ) : null}
          {prevYearChange ? (
            <div className="netWorthDelta">
              <span className="label">vs {prevYearChange.compare_month}</span>
              <span className={prevYearChange.abs >= 0 ? "good" : "bad"}>
                {formatDelta(prevYearChange.abs, prevYearChange.pct)}
              </span>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="kpirow">
        <div className="kpi">
          <div className="label">Stocks / Funds</div>
          <div className="val">{formatMoney(summary?.net_worth.stocks_funds)}</div>
          <Link className="kpiDetailLink" to="/holdings">Open details</Link>
        </div>
        <div className="kpi">
          <div className="label">Cash</div>
          <div className="val">{formatMoney(summary?.net_worth.cash)}</div>
          <Link className="kpiDetailLink" to="/cash">Open details</Link>
        </div>
        <div className="kpi">
          <div className="label">Crypto</div>
          <div className="val">{formatMoney(summary?.net_worth.crypto)}</div>
          <Link className="kpiDetailLink" to="/crypto/holdings">Open details</Link>
        </div>
        <div className="kpi">
          <div className="label">Cash Flow</div>
          <div className="val">{formatMoney(cashFlowNet)}</div>
          <div className="delta muted">{cashFlowMonth ?? "Current month"}</div>
          <Link className="kpiDetailLink" to="/cash-flow">Open details</Link>
        </div>
        <div className="kpi">
          <div className="label">Liabilities</div>
          <div className="val">{formatMoney(summary?.net_worth.liabilities)}</div>
          <Link className="kpiDetailLink" to="/credit-cards">Open details</Link>
        </div>
      </div>

      <div className="bar" title="Allocation (cash/stocks/crypto)">
        <span style={{ width: `${cashPct.toFixed(1)}%`, background: "var(--alloc-cash)" }}></span>
        <span style={{ width: `${stocksPct.toFixed(1)}%`, background: "var(--alloc-stocks)" }}></span>
        <span style={{ width: `${cryptoPct.toFixed(1)}%`, background: "var(--alloc-crypto)" }}></span>
      </div>

      <div className="legend">
        <span className="dot">
          <i style={{ background: "var(--alloc-cash)" }}></i>Cash {cashPct.toFixed(1)}%
        </span>
        <span className="dot">
          <i style={{ background: "var(--alloc-stocks)" }}></i>Stocks {stocksPct.toFixed(1)}%
        </span>
        <span className="dot">
          <i style={{ background: "var(--alloc-crypto)" }}></i>Crypto {cryptoPct.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}
