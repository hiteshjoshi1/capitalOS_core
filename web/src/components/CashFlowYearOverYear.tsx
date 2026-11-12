// #409 (U15, D-113): Cash Flow against the same month last year, and the savings-rate line.
import type { CashFlowTrendPoint, CashFlowYearOverYear } from "../lib/api";
import * as fmt from "../lib/format";
import { DeltaArrow } from "./Delta";
import TrendBarChart from "./TrendBarChart";
import { averageSavingsRate, savingsRateLabel, savingsRatePoints, yearAgoLabel, yearOverYearMovers } from "../lib/yearOverYear";
import "./CashFlowYearOverYear.css";

type FormatMoney = (value?: number | null, decimals?: number) => string;

/** Spending by category against the same month last year (Expenses tab). */
export function YearOverYearSection({ yoy, formatMoney }: { yoy: CashFlowYearOverYear | null | undefined; formatMoney: FormatMoney }) {
  if (!yoy) return null;
  const label = yearAgoLabel(yoy);
  const movers = yearOverYearMovers(yoy.outflow_category_deltas);
  const spendChange = yoy.outflows - yoy.prior_outflows;
  return (
    <section aria-label="Same month last year">
      <div className="cashFlowSectionHeading">
        <p className="wealthEyebrow">Seasonal view</p>
        <h2 className="cashFlowSectionTitle">{`Vs. ${label}`}</h2>
        {yoy.basis === "month_to_date" ? <p className="muted">Day for day, so a part month compares fairly.</p> : null}
      </div>
      <div className="card">
        {!yoy.has_prior_year_data ? (
          <p className="muted">{`No transactions recorded for ${fmt.formatMonth(yoy.prior_year_month)} yet, so there's nothing to compare with.`}</p>
        ) : (
          <>
            <p className="cfYoySummary">
              {`Spent ${formatMoney(yoy.outflows, 0)} vs ${formatMoney(yoy.prior_outflows, 0)} `}
              <strong className={spendChange > 0 ? "bad" : spendChange < 0 ? "good" : undefined}>
                {`(${spendChange >= 0 ? "+" : "−"}${formatMoney(Math.abs(spendChange), 0)})`}
              </strong>
              {yoy.savings_rate != null && yoy.prior_savings_rate != null
                ? ` · saved ${fmt.formatPercent(yoy.savings_rate)} vs ${fmt.formatPercent(yoy.prior_savings_rate)}`
                : ""}
            </p>
            {movers.length === 0 ? (
              <p className="muted">No category moved against last year.</p>
            ) : (
              <div className="cashFlowDriverList">
                {movers.map((item) => {
                  const up = item.delta_amount > 0;
                  return (
                    <div className="cashFlowDriverRow" key={item.label}>
                      <span className="cashFlowDriverLabel">{item.label}</span>
                      <span className="cashFlowDriverValues">
                        <span className="muted">{`${formatMoney(Math.abs(item.current_amount), 0)} vs ${formatMoney(Math.abs(item.prior_amount), 0)}`}</span>
                        <strong className={up ? "bad" : "good"}>
                          <DeltaArrow direction={up ? "up" : "down"} />
                          {`${up ? "+" : "−"}${formatMoney(Math.abs(item.delta_amount), 0)}`}
                        </strong>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

/** The savings rate for the twelve months ending at the month (Overview tab). */
export function SavingsRateTrend({ trend, month }: { trend: CashFlowTrendPoint[] | undefined; month: string }) {
  const points = savingsRatePoints(trend);
  if (points.length === 0 || points.every((p) => p.percent == null)) return null;
  const average = averageSavingsRate(trend);
  return (
    <section aria-label="Savings rate trend">
      <div className="cashFlowSectionHeading cfYoyHeading">
        <div>
          <p className="wealthEyebrow">History</p>
          <h2 className="cashFlowSectionTitle">Savings rate, twelve months</h2>
        </div>
        <span className="muted">
          {`Ending ${fmt.formatMonth(month)}`}
          {average != null ? ` · ${fmt.formatPercent(average, { scale: "points" })} of income saved overall` : ""}
        </span>
      </div>
      <div className="card">
        <TrendBarChart
          ariaLabel="Savings rate by month"
          points={points.map((point) => ({
            month: point.month,
            value: point.barPercent ?? 0,
            displayValue: savingsRateLabel(point),
            tone: point.percent == null ? "neutral" : point.percent >= 0 ? "positive" : "negative",
          }))}
        />
      </div>
    </section>
  );
}
