import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import type {
  CashFlowBreakdownItem,
  CashFlowCategoryDeltaItem,
  CashFlowDetail,
  CashFlowDiagnosticAnswer,
  CashFlowTransaction,
  CategoryTaxonomy,
} from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import TrendBarChart from "../components/TrendBarChart";
import StackedBar from "../components/StackedBar";
import SegmentedToggle from "../components/SegmentedToggle";

type LoadState = "idle" | "loading" | "ready" | "error";
type MerchantsView = "all" | "dining";
type CashFlowWorkspaceTab = "overview" | "income" | "expenses";

type CategoryGroup = {
  label: string;
  options: CategoryTaxonomy[];
};

type TransactionTableProps = {
  title: string;
  emptyMessage: string;
  transactions: CashFlowTransaction[];
  categoryGroups: CategoryGroup[];
  overrideSelections: Record<number, string>;
  pendingOverrides: Record<number, boolean>;
  overrideErrors: Record<number, string>;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<void>;
  pageSize?: number;
};

const CHART_COLORS = [
  "#7dd3fc",
  "#67d6a3",
  "#f7c97b",
  "#b794f4",
  "#ff8d7a",
  "#2ebac6",
  "#f4cf5d",
  "#8f9db2",
];

const DINING_CATEGORY_KEYWORDS = [
  "dining",
  "restaurant",
  "eat out",
  "eat-out",
  "food delivery",
  "delivery",
  "cafe",
  "coffee",
];

function asDate(ts: string) {
  return ts.slice(0, 10);
}

function formatOriginalAmount(transaction: CashFlowTransaction) {
  return `${transaction.currency} ${transaction.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function groupCategories(categories: CategoryTaxonomy[]) {
  const childrenByParent = new Map<number, CategoryTaxonomy[]>();
  const parentById = new Map<number, CategoryTaxonomy>();
  const orphanCategories: CategoryTaxonomy[] = [];

  for (const category of categories) {
    if (category.parent_id == null) {
      parentById.set(category.id, category);
      continue;
    }

    const children = childrenByParent.get(category.parent_id) ?? [];
    children.push(category);
    childrenByParent.set(category.parent_id, children);
  }

  const groups: CategoryGroup[] = [];
  for (const category of categories) {
    if (category.parent_id != null) {
      continue;
    }

    const children = childrenByParent.get(category.id) ?? [];
    groups.push({
      label: category.name,
      options: children.length > 0 ? children : [category],
    });
  }

  for (const [parentId, children] of childrenByParent.entries()) {
    if (!parentById.has(parentId)) {
      orphanCategories.push(...children);
    }
  }

  if (orphanCategories.length > 0) {
    groups.push({ label: "Other", options: orphanCategories });
  }

  return groups;
}

function defaultSelectionValue(transaction: CashFlowTransaction) {
  return transaction.resolved_category_id == null ? "" : String(transaction.resolved_category_id);
}

function formatPercent(value?: number | null) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function conicGradient(items: CashFlowBreakdownItem[]) {
  let offset = 0;
  const parts: string[] = [];
  items.forEach((item, idx) => {
    const next = Math.min(100, offset + Math.max(0, item.percent * 100));
    parts.push(`${CHART_COLORS[idx % CHART_COLORS.length]} ${offset.toFixed(2)}% ${next.toFixed(2)}%`);
    offset = next;
  });
  if (offset < 100) {
    parts.push(`color-mix(in srgb, var(--line) 65%, transparent 35%) ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

function isDiningExpenseTransaction(transaction: CashFlowTransaction) {
  const categoryText = `${transaction.resolved_category ?? ""} ${transaction.raw_category ?? ""}`.toLowerCase();
  return DINING_CATEGORY_KEYWORDS.some((keyword) => categoryText.includes(keyword));
}

function topDiningMerchantItems(transactions: CashFlowTransaction[]): CashFlowBreakdownItem[] {
  const merchantTotals = new Map<string, number>();

  for (const transaction of transactions) {
    if (!isDiningExpenseTransaction(transaction)) {
      continue;
    }
    const merchant = (transaction.merchant_counterparty || transaction.resolved_category || "Unknown").trim() || "Unknown";
    const amount = Math.abs(transaction.base_amount ?? 0);
    merchantTotals.set(merchant, (merchantTotals.get(merchant) ?? 0) + amount);
  }

  const total = Array.from(merchantTotals.values()).reduce((sum, value) => sum + value, 0);
  return _sortedBreakdownItemsFromMap(merchantTotals, total, 5);
}

function _sortedBreakdownItemsFromMap(
  items: Map<string, number>,
  total: number,
  limit?: number,
): CashFlowBreakdownItem[] {
  const ranked = Array.from(items.entries()).sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]));
  const sliced = limit == null ? ranked : ranked.slice(0, limit);
  return sliced.map(([label, amount]) => ({
    label,
    amount,
    percent: total > 0 ? amount / total : 0,
  }));
}

function resolveWorkspaceTab(pathname: string): CashFlowWorkspaceTab {
  if (pathname === "/cash-flow/income") {
    return "income";
  }
  if (pathname === "/cash-flow/expenses") {
    return "expenses";
  }
  return "overview";
}

function findAnswer(answers: CashFlowDiagnosticAnswer[], question: string) {
  return answers.find((answer) => answer.question === question)?.answer ?? "Not enough data to answer this question for the selected month yet.";
}

function DistributionCard({
  title,
  subtitle,
  items,
  total,
  ariaLabel,
  formatMoney,
}: {
  title: string;
  subtitle: string;
  items: CashFlowBreakdownItem[];
  total: number;
  ariaLabel: string;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
}) {
  const topItems = items.slice(0, 6);
  const chartStyle = topItems.length > 0 ? { background: conicGradient(topItems) } : undefined;

  return (
    <article className="card wealthDetailCard cashFlowInsightCard">
      <div className="cashFlowCardHeader">
        <div>
          <p className="wealthEyebrow">{title}</p>
          <h2 className="cashFlowCardTitle">{subtitle}</h2>
        </div>
        <span className="muted">{formatMoney(total)}</span>
      </div>

      {topItems.length > 0 ? (
        <div className="cashFlowDonutLayout">
          <div className="cashFlowDonutChart" style={chartStyle} aria-label={ariaLabel}>
            <div className="cashFlowDonutCenter">
              <span className="label">Share</span>
              <strong>{formatMoney(total)}</strong>
            </div>
          </div>
          <div className="cashFlowLegendList">
            {topItems.map((item, idx) => (
              <div key={`${title}-${item.label}`} className="cashFlowLegendRow">
                <span className="cashFlowLegendLabel">
                  <i style={{ background: CHART_COLORS[idx % CHART_COLORS.length] }}></i>
                  <span className="cashFlowLegendText">{item.label}</span>
                </span>
                <span>{formatPercent(item.percent)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="muted">No category data for this month.</p>
      )}
    </article>
  );
}

function BreakdownBarsCard({
  title,
  subtitle,
  items,
  ariaLabel,
  formatMoney,
}: {
  title: string;
  subtitle: string;
  items: CashFlowBreakdownItem[];
  ariaLabel: string;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
}) {
  const maxAmount = items.reduce((largest, item) => Math.max(largest, item.amount), 0);

  return (
    <article className="card wealthDetailCard cashFlowInsightCard">
      <div className="cashFlowCardHeader">
        <div>
          <p className="wealthEyebrow">{title}</p>
          <h2 className="cashFlowCardTitle">{subtitle}</h2>
        </div>
      </div>

      {items.length > 0 ? (
        <div className="cashFlowBarList" aria-label={ariaLabel}>
          {items.slice(0, 6).map((item, idx) => (
            <div key={`${title}-${item.label}`} className="cashFlowBarRow">
              <div className="cashFlowBarMeta">
                <strong>{item.label}</strong>
                <span className="muted">{formatMoney(item.amount)}</span>
              </div>
              <div className="cashFlowBarTrack">
                <span
                  className="cashFlowBarFill"
                  style={{
                    width: `${maxAmount > 0 ? (item.amount / maxAmount) * 100 : 0}%`,
                    background: CHART_COLORS[idx % CHART_COLORS.length],
                  }}
                />
              </div>
              <span className="cashFlowBarPercent">{formatPercent(item.percent)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No category data for this month.</p>
      )}
    </article>
  );
}

function SplitCard({
  title,
  subtitle,
  items,
  formatMoney,
  colors,
}: {
  title: string;
  subtitle: string;
  items: CashFlowBreakdownItem[];
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  colors?: string[];
}) {
  const palette = colors ?? CHART_COLORS;
  return (
    <article className="card wealthDetailCard cashFlowInsightCard">
      <div className="cashFlowCardHeader">
        <div>
          <p className="wealthEyebrow">{title}</p>
          <h2 className="cashFlowCardTitle">{subtitle}</h2>
        </div>
      </div>

      {items.length > 0 ? (
        <StackedBar
          ariaLabel={subtitle}
          segments={items.map((item, idx) => ({
            key: item.label,
            label: item.label,
            percent: item.percent * 100,
            color: palette[idx % palette.length],
            valueLabel: `${formatMoney(item.amount)} (${formatPercent(item.percent)})`,
          }))}
        />
      ) : (
        <p className="muted">No split available for this month.</p>
      )}
    </article>
  );
}

function DeltaTableCard({
  title,
  subtitle,
  items,
  formatMoney,
}: {
  title: string;
  subtitle: string;
  items: CashFlowCategoryDeltaItem[];
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
}) {
  return (
    <article className="card wealthDetailCard cashFlowInsightCard">
      <div className="cashFlowCardHeader">
        <div>
          <p className="wealthEyebrow">{title}</p>
          <h2 className="cashFlowCardTitle">{subtitle}</h2>
        </div>
      </div>

      {items.length > 0 ? (
        <div className="tableWrap">
        <table className="table cashFlowMiniTable">
          <thead>
            <tr>
              <th>Category</th>
              <th className="right">Current</th>
              <th className="right">Delta</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 5).map((item) => (
              <tr key={`${title}-${item.label}`}>
                <td>{item.label}</td>
                <td className="right">{formatMoney(item.current_amount)}</td>
                <td className={`right ${item.delta_amount > 0 ? "bad" : "good"}`}>
                  {item.delta_amount >= 0 ? "+" : ""}
                  {formatMoney(item.delta_amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      ) : (
        <p className="muted">No month-over-month deterioration was detected.</p>
      )}
    </article>
  );
}

function TrendCard({
  title,
  subtitle,
  points,
  valueKey,
  formatValue,
  ariaLabel,
}: {
  title: string;
  subtitle: string;
  points: CashFlowDetail["analytics"]["trend"];
  valueKey: "net" | "savings_rate";
  formatValue: (value: number | null) => string;
  ariaLabel: string;
}) {
  const values = points.map((point) => point[valueKey] ?? 0);
  const maxMagnitude = values.reduce((largest, value) => Math.max(largest, Math.abs(value)), 0);

  return (
    <article className="card wealthDetailCard cashFlowInsightCard">
      <div className="cashFlowCardHeader">
        <div>
          <p className="wealthEyebrow">{title}</p>
          <h2 className="cashFlowCardTitle">{subtitle}</h2>
        </div>
      </div>

      {points.length > 0 ? (
        <div className="cashFlowTrendList" aria-label={ariaLabel}>
          {points.map((point) => {
            const value = point[valueKey] ?? 0;
            return (
              <div key={`${title}-${point.month}`} className="cashFlowTrendRow">
                <span className="cashFlowTrendMonth">{point.month}</span>
                <div className="cashFlowTrendTrack">
                  <span
                    className={`cashFlowTrendFill ${value >= 0 ? "positive" : "negative"}`}
                    style={{ width: `${maxMagnitude > 0 ? (Math.abs(value) / maxMagnitude) * 100 : 0}%` }}
                  />
                </div>
                <span className="cashFlowTrendValue">{formatValue(point[valueKey])}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="muted">Trend data is not available yet.</p>
      )}
    </article>
  );
}

function WaterfallCard({
  waterfall,
  formatMoney,
}: {
  waterfall: CashFlowDetail["analytics"]["waterfall"];
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
}) {
  const steps = [
    { label: "Starting cash", value: waterfall.starting_cash },
    { label: "Inflows", value: waterfall.inflows },
    { label: "Outflows", value: -waterfall.outflows },
    ...(waterfall.transfers_and_funding != null && Math.abs(waterfall.transfers_and_funding) >= 0.01
      ? [{ label: "Transfers & funding", value: waterfall.transfers_and_funding }]
      : []),
    ...(waterfall.investment_and_fx_effects != null && Math.abs(waterfall.investment_and_fx_effects) >= 0.01
      ? [{ label: "Investment settlements & FX", value: waterfall.investment_and_fx_effects }]
      : waterfall.other_cash_movements != null && Math.abs(waterfall.other_cash_movements) >= 0.01
        ? [{ label: "Other cash movements", value: waterfall.other_cash_movements }]
      : []),
    { label: "Ending cash", value: waterfall.ending_cash },
  ];

  const maxMagnitude = steps.reduce((largest, step) => Math.max(largest, Math.abs(step.value ?? 0)), 0);

  return (
    <article className="card wealthDetailCard cashFlowInsightCard">
      <div className="cashFlowCardHeader">
        <div>
          <p className="wealthEyebrow">Overall cash-flow health</p>
          <h2 className="cashFlowCardTitle">Cash reconciliation</h2>
        </div>
      </div>

      {waterfall.snapshot_start_as_of && waterfall.snapshot_end_as_of ? (
        <p className="muted">
          Reconciled across available cash snapshots from {waterfall.snapshot_start_as_of.slice(0, 10)} to {waterfall.snapshot_end_as_of.slice(0, 10)}.
        </p>
      ) : null}

      {!waterfall.boundary_exact ? (
        <div className="cashFlowUnavailableState" aria-label="Cash reconciliation unavailable">
          <p className="muted">
            {waterfall.availability_message ?? "Cash reconciliation is unavailable for the full month boundary."}
          </p>
          <p className="muted">
            Upload statements or refresh balances to close the month cleanly before using this reconciliation view.
          </p>
        </div>
      ) : (
        <div className="cashFlowWaterfall" aria-label="Cash waterfall chart">
          {steps.map((step) => {
            const value = step.value ?? 0;
            return (
              <div key={step.label} className="cashFlowWaterfallStep">
                <span className="cashFlowWaterfallLabel">{step.label}</span>
                <div className="cashFlowWaterfallTrack">
                  <span
                    className={`cashFlowWaterfallFill ${value >= 0 ? "positive" : "negative"}`}
                    style={{ height: `${maxMagnitude > 0 ? (Math.abs(value) / maxMagnitude) * 100 : 0}%` }}
                  />
                </div>
                <strong>{formatMoney(step.value, 0)}</strong>
              </div>
            );
          })}
        </div>
      )}
    </article>
  );
}

function TransactionTable({
  title,
  emptyMessage,
  transactions: allTransactions,
  categoryGroups,
  overrideSelections,
  pendingOverrides,
  overrideErrors,
  formatMoney,
  onSelectionChange,
  onSave,
  pageSize,
}: TransactionTableProps) {
  const [visibleCount, setVisibleCount] = useState(pageSize ?? allTransactions.length);
  const transactions = pageSize ? allTransactions.slice(0, visibleCount) : allTransactions;

  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="cashFlowTableWrap">
        <table className="table cashFlowTable">
          <thead>
            <tr>
              <th>Date</th>
              <th>Account</th>
              <th>Merchant</th>
              <th>Resolved Category</th>
              <th>Source</th>
              <th>Edit Category</th>
              <th className="right">Original</th>
              <th className="right">Base</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((transaction) => {
              const currentSelection = defaultSelectionValue(transaction);
              const selectedValue = overrideSelections[transaction.transaction_id] ?? currentSelection;
              const categoryId = Number(selectedValue);
              const isDirty = selectedValue !== currentSelection;
              const canSave = Number.isFinite(categoryId) && categoryId > 0 && isDirty;

              return (
                <tr key={transaction.transaction_id}>
                  <td>{asDate(transaction.ts)}</td>
                  <td>
                    <div>{transaction.account_name}</div>
                    <div className="muted">{transaction.account_type}</div>
                  </td>
                  <td>{transaction.merchant_counterparty ?? "—"}</td>
                  <td>
                    <div>{transaction.resolved_category}</div>
                    <div className="muted">{transaction.raw_category ?? "—"}</div>
                  </td>
                  <td>
                    <span className="tag">{transaction.category_source}</span>
                  </td>
                  <td>
                    <div className="cashFlowEditor">
                      <select
                        className="input overrideSelect"
                        aria-label={`Select category for transaction ${transaction.transaction_id}`}
                        value={selectedValue}
                        disabled={pendingOverrides[transaction.transaction_id]}
                        onChange={(event) => onSelectionChange(transaction.transaction_id, event.target.value)}
                      >
                        <option value="">Select category</option>
                        {categoryGroups.map((group) => (
                          <optgroup key={group.label} label={group.label}>
                            {group.options.map((category) => (
                              <option key={category.id} value={category.id}>
                                {category.name}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                      <button
                        className="btn"
                        type="button"
                        aria-label={`Save category for transaction ${transaction.transaction_id}`}
                        disabled={!canSave || pendingOverrides[transaction.transaction_id]}
                        onClick={() => {
                          if (!canSave) {
                            return;
                          }
                          void onSave(transaction.transaction_id, categoryId);
                        }}
                      >
                        {pendingOverrides[transaction.transaction_id] ? "Saving..." : "Save"}
                      </button>
                    </div>
                    {overrideErrors[transaction.transaction_id] ? (
                      <div className="overrideError">{overrideErrors[transaction.transaction_id]}</div>
                    ) : null}
                  </td>
                  <td className={`right ${transaction.amount < 0 ? "bad" : "good"}`}>
                    {formatOriginalAmount(transaction)}
                  </td>
                  <td className={`right ${transaction.base_amount < 0 ? "bad" : "good"}`}>
                    {formatMoney(transaction.base_amount, 2)}
                  </td>
                </tr>
              );
            })}
            {transactions.length === 0 && (
              <tr>
                <td className="muted" colSpan={8}>{emptyMessage}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pageSize && allTransactions.length > 0 ? (
        <div className="footer">
          <span className="muted">
            Showing {Math.min(visibleCount, allTransactions.length)} of {allTransactions.length} transactions
          </span>
          {visibleCount < allTransactions.length ? (
            <button
              className="btn footerAction"
              type="button"
              onClick={() => setVisibleCount((current) => current + pageSize)}
            >
              Show more
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function HeroSection({
  detail,
  formatMoney,
}: {
  detail: CashFlowDetail;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
}) {
  return (
    <section className="cashFlowHeroGrid">
      <article className="card wealthHeroCard cashFlowHeroCard">
        <div className="cashFlowCardHeader">
          <div>
            <p className="wealthEyebrow">Headline KPIs</p>
            <h2 className="cashFlowHeroTitle">Net cash flow</h2>
          </div>
          {detail.analytics.free_cash_flow_change_vs_prior_month != null ? (
            <span className={`wealthHeroChip ${detail.analytics.free_cash_flow_change_vs_prior_month >= 0 ? "wealthHeroChipPositive" : "wealthHeroChipNegative"}`}>
              {detail.analytics.free_cash_flow_change_vs_prior_month >= 0 ? "+" : ""}
              {formatMoney(detail.analytics.free_cash_flow_change_vs_prior_month)}
            </span>
          ) : null}
        </div>
        <div className={`wealthHeroValue ${detail.net >= 0 ? "good" : "bad"}`}>{formatMoney(detail.net, 0)}</div>
        <p className="muted">
          {detail.analytics.prior_month
            ? `vs ${detail.analytics.prior_month}: ${formatMoney(detail.analytics.prior_month_net)}`
            : "Prior-month comparison unavailable."}
        </p>
        <div className="cashFlowHeroActions">
          <Link className="wealthInlineLink" to="/cash-flow/map-transactions">Open Map Transactions</Link>
          <span className="muted">Saved {formatPercent(detail.savings_rate)} · Burn {formatPercent(detail.analytics.burn_rate)}</span>
        </div>
      </article>

      <section className="cashFlowKpiGrid">
        <article className="card wealthDetailCard cashFlowKpiCard">
          <p className="wealthEyebrow">Total inflows</p>
          <h2 className="wealthDetailTitle">{formatMoney(detail.income_total)}</h2>
        </article>
        <article className="card wealthDetailCard cashFlowKpiCard">
          <p className="wealthEyebrow">Total outflows</p>
          <h2 className="wealthDetailTitle">{formatMoney(detail.expense_total)}</h2>
        </article>
        <article className="card wealthDetailCard cashFlowKpiCard">
          <p className="wealthEyebrow">Savings rate</p>
          <h2 className="wealthDetailTitle">{formatPercent(detail.savings_rate)}</h2>
        </article>
        <article className="card wealthDetailCard cashFlowKpiCard">
          <p className="wealthEyebrow">Burn rate</p>
          <h2 className="wealthDetailTitle">{formatPercent(detail.analytics.burn_rate)}</h2>
        </article>
      </section>
    </section>
  );
}

function OverviewTab({
  detail,
  formatMoney,
}: {
  detail: CashFlowDetail;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
}) {
  return (
    <>
      <HeroSection detail={detail} formatMoney={formatMoney} />

      <section className="cashFlowSectionGrid">
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Overview</p>
          <h2 className="cashFlowSectionTitle">High-level diagnostics for the selected month</h2>
        </div>
        <div className="cashFlowInsightGrid cashFlowInsightGridTwoUp">
          <article className="card wealthDetailCard cashFlowInsightCard">
            <div className="cashFlowCardHeader">
              <div>
                <p className="wealthEyebrow">Health</p>
                <h2 className="cashFlowCardTitle">Six-month net cash flow</h2>
              </div>
            </div>
            {detail.analytics.trend.length > 0 ? (
              <TrendBarChart
                ariaLabel="Net cash flow trend by month"
                points={detail.analytics.trend.map((point) => ({
                  month: point.month,
                  value: point.net ?? 0,
                  displayValue: formatMoney(point.net, 0),
                  tone: (point.net ?? 0) >= 0 ? "positive" : "negative",
                }))}
              />
            ) : (
              <p className="muted">Trend data is not available yet.</p>
            )}
          </article>
          <DistributionCard
            title="Money in"
            subtitle="Compact inflow composition"
            items={detail.analytics.inflow_source_mix}
            total={detail.income_total}
            ariaLabel="Compact inflow composition"
            formatMoney={formatMoney}
          />
          <DistributionCard
            title="Money out"
            subtitle="Compact outflow composition"
            items={detail.analytics.outflow_categories}
            total={detail.expense_total}
            ariaLabel="Compact outflow composition"
            formatMoney={formatMoney}
          />
        </div>
      </section>

      <section className="cashFlowSectionGrid">
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">What changed</p>
          <h2 className="cashFlowSectionTitle">Month-over-month summary and overall health</h2>
        </div>
        <div className="cashFlowAnswerGrid cashFlowAnswerGridTwoUp">
          <article className="card wealthDetailCard cashFlowAnswerCard">
            <p className="wealthEyebrow">Concise change summary</p>
            <h2 className="cashFlowCardTitle">What changed versus last month?</h2>
            <p className="muted">{findAnswer(detail.analytics.answers, "What changed versus last month?")}</p>
          </article>
          <article className="card wealthDetailCard cashFlowAnswerCard">
            <p className="wealthEyebrow">Saved vs spent</p>
            <h2 className="cashFlowCardTitle">How much of my income was saved vs spent?</h2>
            <p className="muted">{findAnswer(detail.analytics.answers, "How much of my income was saved vs spent?")}</p>
          </article>
          <DeltaTableCard
            title="Drivers"
            subtitle="Categories behind free cash flow deterioration"
            items={detail.analytics.deterioration_drivers}
            formatMoney={formatMoney}
          />
          <TrendCard
            title="Health"
            subtitle="Savings rate trend"
            points={detail.analytics.trend}
            valueKey="savings_rate"
            formatValue={formatPercent}
            ariaLabel="Savings rate trend by month"
          />
          <WaterfallCard waterfall={detail.analytics.waterfall} formatMoney={formatMoney} />
        </div>
      </section>
    </>
  );
}

function IncomeTab({
  detail,
  categoryGroups,
  overrideSelections,
  pendingOverrides,
  overrideErrors,
  formatMoney,
  onSelectionChange,
  onSave,
}: {
  detail: CashFlowDetail;
  categoryGroups: CategoryGroup[];
  overrideSelections: Record<number, string>;
  pendingOverrides: Record<number, boolean>;
  overrideErrors: Record<number, string>;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<void>;
}) {
  return (
    <>
      <section className="cashFlowSectionGrid">
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Income</p>
          <h2 className="cashFlowSectionTitle">What funded the month and how concentrated it was</h2>
        </div>
        <div className="cashFlowInsightGrid cashFlowInsightGridTwoUp">
          <article className="card wealthDetailCard cashFlowAnswerCard">
            <p className="wealthEyebrow">Direct answer</p>
            <h2 className="cashFlowCardTitle">What percentage of inflows came from salary, dividends, and transfers?</h2>
            <p className="muted">{findAnswer(detail.analytics.answers, "What percentage of inflows came from salary, dividends, and transfers?")}</p>
          </article>
          <DistributionCard
            title="Money in"
            subtitle="Income source composition"
            items={detail.analytics.inflow_source_mix}
            total={detail.income_total}
            ariaLabel="Income source donut chart"
            formatMoney={formatMoney}
          />
          <SplitCard
            title="Money in"
            subtitle="Recurring vs one-off inflows"
            items={detail.analytics.inflow_recurring_split}
            formatMoney={formatMoney}
          />
        </div>
      </section>

      <section className="cashFlowSectionGrid">
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Income audit trail</p>
          <h2 className="cashFlowSectionTitle">Income transactions and category evidence</h2>
        </div>
        <TransactionTable
          title={`Income transactions (${detail.income.transaction_count})`}
          emptyMessage={`No income transactions for ${detail.month}.`}
          transactions={detail.income.transactions}
          categoryGroups={categoryGroups}
          overrideSelections={overrideSelections}
          pendingOverrides={pendingOverrides}
          overrideErrors={overrideErrors}
          formatMoney={formatMoney}
          onSelectionChange={onSelectionChange}
          onSave={onSave}
        />
      </section>
    </>
  );
}

function ExpensesTab({
  detail,
  categoryGroups,
  overrideSelections,
  pendingOverrides,
  overrideErrors,
  formatMoney,
  onSelectionChange,
  onSave,
}: {
  detail: CashFlowDetail;
  categoryGroups: CategoryGroup[];
  overrideSelections: Record<number, string>;
  pendingOverrides: Record<number, boolean>;
  overrideErrors: Record<number, string>;
  formatMoney: (value?: number | null, maximumFractionDigits?: number) => string;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<void>;
}) {
  const [merchantsView, setMerchantsView] = useState<MerchantsView>("all");
  const diningMerchants = topDiningMerchantItems(detail.expenses.transactions);
  const activeMerchantItems: CashFlowBreakdownItem[] =
    merchantsView === "dining"
      ? diningMerchants
      : detail.analytics.top_outflow_merchants.map((m) => ({ label: m.merchant, amount: m.amount, percent: m.percent }));

  return (
    <>
      <section className="cashFlowSectionGrid">
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Expenses</p>
          <h2 className="cashFlowSectionTitle">Where money went, who captured it, and what deteriorated</h2>
        </div>
        <div className="cashFlowAnswerGrid cashFlowAnswerGridTwoUp">
          <article className="card wealthDetailCard cashFlowAnswerCard">
            <p className="wealthEyebrow">Direct answer</p>
            <h2 className="cashFlowCardTitle">Where did my money go this month?</h2>
            <p className="muted">{findAnswer(detail.analytics.answers, "Where did my money go this month?")}</p>
          </article>
          <article className="card wealthDetailCard cashFlowAnswerCard">
            <p className="wealthEyebrow">Recurring pressure</p>
            <h2 className="cashFlowCardTitle">Which recurring expenses are driving most of my outflows?</h2>
            <p className="muted">{findAnswer(detail.analytics.answers, "Which recurring expenses are driving most of my outflows?")}</p>
          </article>
        </div>
        <div className="cashFlowInsightGrid cashFlowInsightGridTwoUp">
          <DistributionCard
            title="Money out"
            subtitle="Top expense categories"
            items={detail.analytics.outflow_categories}
            total={detail.expense_total}
            ariaLabel="Top expense categories donut chart"
            formatMoney={formatMoney}
          />
          <BreakdownBarsCard
            title="Money out"
            subtitle="Spend by category"
            items={detail.analytics.outflow_categories}
            ariaLabel="Monthly spend by category chart"
            formatMoney={formatMoney}
          />
          <SplitCard
            title="Money out"
            subtitle="Recurring vs non-recurring"
            items={detail.analytics.outflow_recurring_split}
            formatMoney={formatMoney}
          />
          <article className="card wealthDetailCard cashFlowInsightCard">
            <div className="cashFlowCardHeader">
              <div>
                <p className="wealthEyebrow">Money out</p>
                <h2 className="cashFlowCardTitle">{merchantsView === "dining" ? "Top dining merchants" : "Top merchants"}</h2>
              </div>
              <SegmentedToggle
                ariaLabel="Merchant view"
                value={merchantsView}
                onChange={setMerchantsView}
                options={[
                  { value: "all", label: "All" },
                  { value: "dining", label: "Dining" },
                ]}
              />
            </div>
            {activeMerchantItems.length > 0 ? (
              <div className="cashFlowBarList" aria-label={merchantsView === "dining" ? "Top dining merchants chart" : "Top merchants chart"}>
                {activeMerchantItems.slice(0, 6).map((item, idx) => {
                  const maxAmount = Math.max(...activeMerchantItems.map((i) => i.amount), 1);
                  return (
                    <div key={`${merchantsView}-${item.label}`} className="cashFlowBarRow">
                      <div className="cashFlowBarMeta">
                        <strong>{item.label}</strong>
                        <span className="muted">{formatMoney(item.amount)}</span>
                      </div>
                      <div className="cashFlowBarTrack">
                        <span
                          className="cashFlowBarFill"
                          style={{ width: `${(item.amount / maxAmount) * 100}%`, background: CHART_COLORS[idx % CHART_COLORS.length] }}
                        />
                      </div>
                      <span className="cashFlowBarPercent">{formatPercent(item.percent)}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="muted">No merchant data for this month.</p>
            )}
          </article>
          <SplitCard
            title="Money out"
            subtitle="Fixed vs variable expenses"
            items={detail.analytics.outflow_fixed_variable_split}
            formatMoney={formatMoney}
            colors={["#4f8cff", "#7d67ff"]}
          />
          <DeltaTableCard
            title="Money out"
            subtitle="Largest deteriorating outflow categories"
            items={detail.analytics.outflow_category_deltas}
            formatMoney={formatMoney}
          />
        </div>
      </section>

      <section className="cashFlowSectionGrid">
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Expense audit trail</p>
          <h2 className="cashFlowSectionTitle">Expense transactions and category controls</h2>
        </div>
        <TransactionTable
          title={`Expense transactions (${detail.expenses.transaction_count})`}
          emptyMessage={`No expense transactions for ${detail.month}.`}
          transactions={detail.expenses.transactions}
          categoryGroups={categoryGroups}
          overrideSelections={overrideSelections}
          pendingOverrides={pendingOverrides}
          overrideErrors={overrideErrors}
          formatMoney={formatMoney}
          onSelectionChange={onSelectionChange}
          onSave={onSave}
          pageSize={8}
        />
      </section>
    </>
  );
}

export default function CashFlowDetailRoute() {
  const location = useLocation();
  const workspaceTab = resolveWorkspaceTab(location.pathname);
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [detail, setDetail] = useState<CashFlowDetail | null>(null);
  const [categories, setCategories] = useState<CategoryTaxonomy[]>([]);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [pendingOverrides, setPendingOverrides] = useState<Record<number, boolean>>({});
  const [overrideErrors, setOverrideErrors] = useState<Record<number, string>>({});
  const [overrideSelections, setOverrideSelections] = useState<Record<number, string>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setState("loading");
      setErr("");
      setPendingOverrides({});
      setOverrideErrors({});
      setOverrideSelections({});

      try {
        const [taxonomy, data] = await Promise.all([
          api.categories(),
          api.cashFlowDetail(month, baseCurrency),
        ]);
        if (cancelled) return;
        setCategories(taxonomy);
        setDetail(data);
        setState("ready");
      } catch (e: unknown) {
        if (cancelled) return;
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [month, baseCurrency]);

  const categoryGroups = useMemo(() => groupCategories(categories), [categories]);
  const effectiveBaseCurrency = detail?.base_currency || baseCurrency;
  const currencyPrefix = effectiveBaseCurrency === "SGD" ? "S$" : effectiveBaseCurrency;
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const shellTitle =
    workspaceTab === "income"
      ? "Income"
      : workspaceTab === "expenses"
        ? "Expenses"
        : "Cash Flow Overview";

  const shellSubtitle =
    workspaceTab === "income"
      ? "A deterministic view of where cash came from, how concentrated it was, and the underlying income transactions."
      : workspaceTab === "expenses"
        ? "A deterministic view of where cash went, which merchants captured it, and the underlying expense transactions."
        : "A deterministic diagnostic workspace for where cash came from, where it went, what changed, and what is driving the move.";

  async function handleSave(transactionId: number, categoryId: number) {
    setPendingOverrides((current) => ({ ...current, [transactionId]: true }));
    setOverrideErrors((current) => {
      const next = { ...current };
      delete next[transactionId];
      return next;
    });

    try {
      await api.categoryOverride({ transaction_id: transactionId, category_id: categoryId });
      const refreshed = await api.cashFlowDetail(month, baseCurrency);
      setDetail(refreshed);
      setOverrideSelections((current) => {
        const next = { ...current };
        delete next[transactionId];
        return next;
      });
    } catch (e: unknown) {
      setOverrideErrors((current) => ({
        ...current,
        [transactionId]:
          e instanceof Error ? e.message : "Save failed. Try again after checking the API state.",
      }));
    } finally {
      setPendingOverrides((current) => {
        const next = { ...current };
        delete next[transactionId];
        return next;
      });
    }
  }

  return (
    <PageShell
      title={shellTitle}
      subtitle={shellSubtitle}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="coPillBtn">
                        <span aria-hidden="true">{baseCurrency}</span>
            <select
              className="coPillBtnInput"
              aria-label="Base currency"
              value={baseCurrency}
              onChange={(event) => setBaseCurrency(event.target.value)}
            >
              <option value="SGD">SGD</option>
              <option value="USD">USD</option>
              <option value="HKD">HKD</option>
              <option value="INR">INR</option>
            </select>
          </label>
        </>
      )}
    >
      {state === "loading" && <div className="card">Loading…</div>}

      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">Cash flow detail unavailable</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && detail ? (
        <div className="cashFlowWorkspace">
          {workspaceTab === "overview" ? <OverviewTab detail={detail} formatMoney={formatMoney} /> : null}
          {workspaceTab === "income" ? (
            <IncomeTab
              detail={detail}
              categoryGroups={categoryGroups}
              overrideSelections={overrideSelections}
              pendingOverrides={pendingOverrides}
              overrideErrors={overrideErrors}
              formatMoney={formatMoney}
              onSelectionChange={(transactionId, value) => {
                setOverrideSelections((current) => ({ ...current, [transactionId]: value }));
              }}
              onSave={handleSave}
            />
          ) : null}
          {workspaceTab === "expenses" ? (
            <ExpensesTab
              detail={detail}
              categoryGroups={categoryGroups}
              overrideSelections={overrideSelections}
              pendingOverrides={pendingOverrides}
              overrideErrors={overrideErrors}
              formatMoney={formatMoney}
              onSelectionChange={(transactionId, value) => {
                setOverrideSelections((current) => ({ ...current, [transactionId]: value }));
              }}
              onSave={handleSave}
            />
          ) : null}
        </div>
      ) : null}
    </PageShell>
  );
}
