import type { DashboardSummary } from "../../lib/api";
import { Link } from "react-router-dom";
import Delta from "../Delta";
import { missingBaselineReason } from "../../lib/delta";
import { formatPercent } from "../../lib/format";

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
  const currency = summary?.base_currency;

  return (
    <div className="card netWorthCard">
      <h2>Net Worth</h2>
      <div className="big">{formatMoney(summary?.net_worth.total)}</div>
      {prevMonthChange || prevYearChange ? (
        <div className="netWorthDeltaRow" role="group" aria-label="Net worth changes">
          {prevMonthChange ? (
            <div className="netWorthDelta">
              <span className="label">vs {prevMonthChange.compare_month}</span>
              <Delta
                abs={prevMonthChange.abs}
                pct={prevMonthChange.pct}
                currency={currency}
                missingReason={missingBaselineReason(prevMonthChange)}
              />
            </div>
          ) : null}
          {prevYearChange ? (
            <div className="netWorthDelta">
              <span className="label">vs {prevYearChange.compare_month}</span>
              <Delta
                abs={prevYearChange.abs}
                pct={prevYearChange.pct}
                currency={currency}
                missingReason={missingBaselineReason(prevYearChange)}
              />
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
          <Link className="kpiDetailLink" to="/liabilities">Open details</Link>
        </div>
      </div>

      <div className="bar" title="Allocation (cash/stocks/crypto)">
        <span style={{ width: `${cashPct.toFixed(1)}%`, background: "var(--alloc-cash)" }}></span>
        <span style={{ width: `${stocksPct.toFixed(1)}%`, background: "var(--alloc-stocks)" }}></span>
        <span style={{ width: `${cryptoPct.toFixed(1)}%`, background: "var(--alloc-crypto)" }}></span>
      </div>

      <div className="legend">
        <span className="dot">
          <i style={{ background: "var(--alloc-cash)" }}></i>Cash {formatPercent(cashPct, { scale: "points" })}
        </span>
        <span className="dot">
          <i style={{ background: "var(--alloc-stocks)" }}></i>Stocks {formatPercent(stocksPct, { scale: "points" })}
        </span>
        <span className="dot">
          <i style={{ background: "var(--alloc-crypto)" }}></i>Crypto {formatPercent(cryptoPct, { scale: "points" })}
        </span>
      </div>
    </div>
  );
}
