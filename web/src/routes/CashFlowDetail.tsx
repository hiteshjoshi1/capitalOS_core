import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";
import type {
  CashFlowBreakdownItem,
  CashFlowCategoryDeltaItem,
  CashFlowDetail,
  CashFlowDiagnosticAnswer,
  CashFlowTransaction,
  CashFlowWaterfall,
  CategoryTaxonomy,
} from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import TrendBarChart from "../components/TrendBarChart";
import SegmentedToggle from "../components/SegmentedToggle";

type LoadState = "idle" | "loading" | "ready" | "error";
type MerchantsView = "all" | "dining";
type CashFlowWorkspaceTab = "overview" | "income" | "expenses";

type CategoryGroup = {
  label: string;
  options: CategoryTaxonomy[];
};

type FormatMoney = (value?: number | null, maximumFractionDigits?: number) => string;

const CHART_COLORS = [
  "#4f8cff",
  "#1fb981",
  "#f59f43",
  "#7d67ff",
  "#ef6ca8",
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

function formatMonthName(month: string): string {
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;
  if (!Number.isFinite(year) || !Number.isFinite(monthIndex)) {
    return month;
  }
  return new Date(year, monthIndex, 1).toLocaleString(undefined, { month: "long" });
}

function formatMonthYear(month: string): string {
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;
  if (!Number.isFinite(year) || !Number.isFinite(monthIndex)) {
    return month;
  }
  return new Date(year, monthIndex, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
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

/** Full-width donut + legend, used standalone by each tab (Where the income came from / Top expense categories). */
function DonutSection({
  eyebrow,
  title,
  items,
  total,
  ariaLabel,
  formatMoney,
}: {
  eyebrow: string;
  title: string;
  items: CashFlowBreakdownItem[];
  total: number;
  ariaLabel: string;
  formatMoney: FormatMoney;
}) {
  return (
    <section>
      <div className="cashFlowSectionHeading">
        <p className="wealthEyebrow">{eyebrow}</p>
        <h2 className="cashFlowSectionTitle">{title}</h2>
      </div>
      {items.length > 0 ? (
        <div className="card cashFlowDonutLayout" style={{ padding: 28 }} aria-label={ariaLabel}>
          <div className="cashFlowDonutChart" style={{ background: conicGradient(items) }}>
            <div className="cashFlowDonutCenter">
              <span className="label">Total</span>
              <strong>{formatMoney(total)}</strong>
            </div>
          </div>
          <div className="cashFlowLegendList">
            {items.map((item, idx) => (
              <div className="cashFlowLegendRow" key={item.label}>
                <span className="cashFlowLegendLabel">
                  <i style={{ background: CHART_COLORS[idx % CHART_COLORS.length] }} />
                  <span className="cashFlowLegendText">{item.label}</span>
                </span>
                <span className="muted">
                  {formatMoney(item.amount)} <strong>{formatPercent(item.percent)}</strong>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="card muted">No category data for this month.</div>
      )}
    </section>
  );
}

/** Two-segment stacked bar + legend (Recurring vs one-off, Fixed vs variable). cardTitle is only
 * used when several of these sit side by side under one shared section heading. */
function SplitBar({
  cardTitle,
  items,
  formatMoney,
  colors,
}: {
  cardTitle?: string;
  items: CashFlowBreakdownItem[];
  formatMoney: FormatMoney;
  colors?: string[];
}) {
  const palette = colors ?? ["var(--accent)", "var(--warn)"];
  return (
    <article className="card cashFlowSplitBarCard">
      {cardTitle ? <p className="cashFlowSplitBarTitle">{cardTitle}</p> : null}
      {items.length > 0 ? (
        <>
          <div className="cashFlowSplitBarTrack" role="img" aria-label={cardTitle ?? "Split"}>
            {items.map((item, idx) => (
              <span
                key={item.label}
                style={{ width: `${Math.max(0, item.percent * 100)}%`, background: palette[idx % palette.length] }}
              />
            ))}
          </div>
          <div className="cashFlowSplitBarLegend">
            {items.map((item, idx) => (
              <span className="cashFlowSplitBarLegendItem" key={item.label}>
                <i style={{ background: palette[idx % palette.length] }} />
                {item.label} — {formatMoney(item.amount)} ({formatPercent(item.percent)})
              </span>
            ))}
          </div>
        </>
      ) : (
        <p className="muted">No split available for this month.</p>
      )}
    </article>
  );
}

/** Label + progress bar + amount + percent, one line per merchant. */
function MerchantRows({ items, formatMoney }: { items: CashFlowBreakdownItem[]; formatMoney: FormatMoney }) {
  if (items.length === 0) {
    return <p className="muted">No merchant data for this month.</p>;
  }
  const maxAmount = Math.max(...items.map((item) => item.amount), 1);
  return (
    <div className="cashFlowMerchantList">
      {items.slice(0, 6).map((item, idx) => (
        <div className="cashFlowMerchantRow" key={item.label}>
          <span className="cashFlowMerchantLabel">{item.label}</span>
          <div className="cashFlowMerchantTrack">
            <span
              style={{ width: `${Math.max(6, (item.amount / maxAmount) * 100)}%`, background: CHART_COLORS[idx % CHART_COLORS.length] }}
            />
          </div>
          <strong className="cashFlowMerchantAmount">{formatMoney(item.amount)}</strong>
          <span className="cashFlowMerchantPercent">{formatPercent(item.percent)}</span>
        </div>
      ))}
    </div>
  );
}

/** Label + current amount + delta, one line per category. Used for "Vs. last month" drivers and
 * "Categories trending up" — both lists only ever surface categories moving in the worse
 * direction, so the delta is always shown as a red "+amount" increase. */
function DriverRows({ items, formatMoney }: { items: CashFlowCategoryDeltaItem[]; formatMoney: FormatMoney }) {
  if (items.length === 0) {
    return <p className="muted">No notable changes this month.</p>;
  }
  return (
    <div className="cashFlowDriverList">
      {items.map((item) => (
        <div className="cashFlowDriverRow" key={item.label}>
          <span className="cashFlowDriverLabel">{item.label}</span>
          <span className="cashFlowDriverValues">
            <span className="muted">{formatMoney(Math.abs(item.current_amount))}</span>
            <strong className="bad">+{formatMoney(Math.abs(item.delta_amount))}</strong>
          </span>
        </div>
      ))}
    </div>
  );
}

/** Column-bar cash bridge (starting cash -> inflows -> outflows -> transfers -> ending cash). */
function CashBridgeSection({ waterfall, formatMoney }: { waterfall: CashFlowWaterfall; formatMoney: FormatMoney }) {
  const steps = [
    { label: "Starting cash", value: waterfall.starting_cash, neutral: true },
    { label: "Inflows", value: waterfall.inflows, neutral: false },
    { label: "Outflows", value: -waterfall.outflows, neutral: false },
    ...(waterfall.transfers_and_funding != null && Math.abs(waterfall.transfers_and_funding) >= 0.01
      ? [{ label: "Transfers & funding", value: waterfall.transfers_and_funding, neutral: false }]
      : waterfall.investment_and_fx_effects != null && Math.abs(waterfall.investment_and_fx_effects) >= 0.01
        ? [{ label: "Investment settlements & FX", value: waterfall.investment_and_fx_effects, neutral: false }]
        : waterfall.other_cash_movements != null && Math.abs(waterfall.other_cash_movements) >= 0.01
          ? [{ label: "Other cash movements", value: waterfall.other_cash_movements, neutral: false }]
          : []),
    { label: "Ending cash", value: waterfall.ending_cash, neutral: true },
  ];

  const maxMagnitude = steps.reduce((largest, step) => Math.max(largest, Math.abs(step.value ?? 0)), 0);

  return (
    <section>
      <div className="cashFlowSectionHeading">
        <p className="wealthEyebrow">Cash bridge</p>
        <h2 className="cashFlowSectionTitle">How your cash balance moved</h2>
        <p className="muted">
          Starting balance, plus what came in and out, plus transfers to other accounts, equals your ending balance.
        </p>
      </div>

      <div className="card" style={{ padding: "28px 24px 20px" }}>
        {waterfall.snapshot_start_as_of && waterfall.snapshot_end_as_of ? (
          <p className="muted" style={{ marginTop: 0 }}>
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
          <div className="cashFlowBridge" aria-label="Cash bridge chart">
            {steps.map((step) => {
              const value = step.value ?? 0;
              return (
                <div key={step.label} className="cashFlowBridgeStep">
                  <span className="cashFlowBridgeValue">{formatMoney(step.value, 0)}</span>
                  <div className="cashFlowBridgeTrack">
                    <span
                      className={`cashFlowBridgeFill ${step.neutral ? "neutral" : value >= 0 ? "positive" : "negative"}`}
                      style={{ height: `${maxMagnitude > 0 ? (Math.abs(value) / maxMagnitude) * 100 : 0}%` }}
                    />
                  </div>
                  <span className="cashFlowBridgeLabel">{step.label}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

type TransactionListSectionProps = {
  title: string;
  emptyMessage: string;
  transactions: CashFlowTransaction[];
  categoryGroups: CategoryGroup[];
  overrideSelections: Record<number, string>;
  pendingOverrides: Record<number, boolean>;
  overrideErrors: Record<number, string>;
  formatMoney: FormatMoney;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<boolean>;
  amountTone: "good" | "bad";
  pageSize?: number;
};

/** Read-only audit-trail rows (merchant/date/account, category tag, amount) — clicking the
 * category tag reveals the existing select+Save editor inline for that one row. */
function TransactionListSection({
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
  amountTone,
  pageSize,
}: TransactionListSectionProps) {
  const [visibleCount, setVisibleCount] = useState(pageSize ?? allTransactions.length);
  const [editingId, setEditingId] = useState<number | null>(null);
  const transactions = pageSize ? allTransactions.slice(0, visibleCount) : allTransactions;

  return (
    <section>
      <div
        className="cashFlowSectionHeading"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}
      >
        <h2 className="cashFlowSectionTitle">{title}</h2>
      </div>
      <div className="card">
        <div className="listRows">
          {transactions.map((transaction) => {
            const isEditing = editingId === transaction.transaction_id;
            const currentSelection = defaultSelectionValue(transaction);
            const selectedValue = overrideSelections[transaction.transaction_id] ?? currentSelection;
            const categoryId = Number(selectedValue);
            const isDirty = selectedValue !== currentSelection;
            const canSave = Number.isFinite(categoryId) && categoryId > 0 && isDirty;
            const isPending = Boolean(pendingOverrides[transaction.transaction_id]);

            return (
              <div className="cashFlowTxn" key={transaction.transaction_id}>
                <div className="listRow liabDueRow cashFlowTxnRow">
                  <div className="listRowMain">
                    <span className="listRowTitle">{transaction.merchant_counterparty || transaction.resolved_category}</span>
                    <span className="listRowMeta">
                      {asDate(transaction.ts)} · {transaction.account_name}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="tag cashFlowTxnCategoryBtn"
                    aria-label={`Edit category for transaction ${transaction.transaction_id}`}
                    onClick={() => setEditingId(isEditing ? null : transaction.transaction_id)}
                  >
                    {transaction.resolved_category}
                  </button>
                  <span className={`listRowValue ${amountTone}`}>{formatMoney(transaction.base_amount, 2)}</span>
                </div>
                {isEditing ? (
                  <div className="cashFlowTxnEditor">
                    <select
                      className="input overrideSelect"
                      aria-label={`Select category for transaction ${transaction.transaction_id}`}
                      value={selectedValue}
                      disabled={isPending}
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
                      disabled={!canSave || isPending}
                      onClick={() => {
                        if (!canSave) return;
                        void onSave(transaction.transaction_id, categoryId).then((succeeded) => {
                          if (succeeded) setEditingId(null);
                        });
                      }}
                    >
                      {isPending ? "Saving..." : "Save"}
                    </button>
                    <button className="btn cashFlowTxnCancelBtn" type="button" onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                    {overrideErrors[transaction.transaction_id] ? (
                      <div className="overrideError">{overrideErrors[transaction.transaction_id]}</div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
          {transactions.length === 0 && <p className="muted">{emptyMessage}</p>}
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
    </section>
  );
}

function OverviewTab({
  detail,
  formatMoney,
}: {
  detail: CashFlowDetail;
  formatMoney: FormatMoney;
}) {
  const delta = detail.analytics.free_cash_flow_change_vs_prior_month;
  const deltaChip =
    delta == null
      ? null
      : {
          text: `${delta >= 0 ? "+" : "-"}${formatMoney(Math.abs(delta))}${
            detail.analytics.prior_month ? ` vs ${formatMonthName(detail.analytics.prior_month)}` : ""
          }`,
          positive: delta >= 0,
        };

  return (
    <>
      <HeroMetricCard
        eyebrow="Net cash flow this month"
        value={`${detail.net >= 0 ? "+" : ""}${formatMoney(detail.net)}`}
        deltaChip={deltaChip}
        insightText={`Saved ${formatPercent(detail.savings_rate)} of income · Burn rate ${formatPercent(detail.analytics.burn_rate)}`}
      />

      <section>
        <div className="cashFlowKpiGrid">
          <article className="card cashFlowKpiCard">
            <p className="wealthEyebrow">Total inflows</p>
            <p className="cashFlowKpiValue">{formatMoney(detail.income_total)}</p>
          </article>
          <article className="card cashFlowKpiCard">
            <p className="wealthEyebrow">Total outflows</p>
            <p className="cashFlowKpiValue">{formatMoney(detail.expense_total)}</p>
          </article>
          <article className="card cashFlowKpiCard">
            <p className="wealthEyebrow">Savings rate</p>
            <p className="cashFlowKpiValue">{formatPercent(detail.savings_rate)}</p>
          </article>
          <article className="card cashFlowKpiCard">
            <p className="wealthEyebrow">Burn rate</p>
            <p className="cashFlowKpiValue">{formatPercent(detail.analytics.burn_rate)}</p>
          </article>
        </div>
      </section>

      <section>
        <div
          className="cashFlowSectionHeading"
          style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}
        >
          <div>
            <p className="wealthEyebrow">History</p>
            <h2 className="cashFlowSectionTitle">Six-month net cash flow</h2>
          </div>
          <span className="muted">Ending {formatMonthYear(detail.month)}</span>
        </div>
        {detail.analytics.trend.length > 0 ? (
          <div className="card">
            <TrendBarChart
              ariaLabel="Net cash flow trend by month"
              points={detail.analytics.trend.map((point) => ({
                month: point.month,
                value: point.net ?? 0,
                displayValue: formatMoney(point.net, 0),
                tone: (point.net ?? 0) >= 0 ? "positive" : "negative",
              }))}
            />
          </div>
        ) : (
          <div className="card muted">Trend data is not available yet.</div>
        )}
      </section>

      <section>
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">What changed</p>
          <h2 className="cashFlowSectionTitle">Vs. last month</h2>
        </div>
        <div className="card">
          <p className="cashFlowNarrative">{findAnswer(detail.analytics.answers, "What changed versus last month?")}</p>
          <DriverRows items={detail.analytics.deterioration_drivers} formatMoney={formatMoney} />
        </div>
      </section>

      <CashBridgeSection waterfall={detail.analytics.waterfall} formatMoney={formatMoney} />
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
  formatMoney: FormatMoney;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<boolean>;
}) {
  return (
    <>
      <HeroMetricCard
        eyebrow="Total inflows this month"
        value={formatMoney(detail.income_total)}
        insightText={findAnswer(detail.analytics.answers, "What percentage of inflows came from salary, dividends, and transfers?")}
      />

      <DonutSection
        eyebrow="Composition"
        title="Where the income came from"
        items={detail.analytics.inflow_source_mix}
        total={detail.income_total}
        ariaLabel="Income source donut chart"
        formatMoney={formatMoney}
      />

      <section>
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Reliability</p>
          <h2 className="cashFlowSectionTitle">Recurring vs. one-off</h2>
        </div>
        <SplitBar items={detail.analytics.inflow_recurring_split} formatMoney={formatMoney} />
      </section>

      <TransactionListSection
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
        amountTone="good"
      />
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
  formatMoney: FormatMoney;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<boolean>;
}) {
  const [merchantsView, setMerchantsView] = useState<MerchantsView>("all");
  const diningMerchants = topDiningMerchantItems(detail.expenses.transactions);
  const activeMerchantItems: CashFlowBreakdownItem[] =
    merchantsView === "dining"
      ? diningMerchants
      : detail.analytics.top_outflow_merchants.map((m) => ({ label: m.merchant, amount: m.amount, percent: m.percent }));

  return (
    <>
      <HeroMetricCard
        eyebrow="Total outflows this month"
        value={formatMoney(detail.expense_total)}
        insightText={findAnswer(detail.analytics.answers, "Where did my money go this month?")}
      />

      <DonutSection
        eyebrow="Composition"
        title="Top expense categories"
        items={detail.analytics.outflow_categories}
        total={detail.expense_total}
        ariaLabel="Top expense categories donut chart"
        formatMoney={formatMoney}
      />

      <section>
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Reliability</p>
          <h2 className="cashFlowSectionTitle">How predictable is your spend</h2>
        </div>
        <div className="cashFlowInsightGridTwoUp">
          <SplitBar
            cardTitle="Recurring vs. non-recurring"
            items={detail.analytics.outflow_recurring_split}
            formatMoney={formatMoney}
          />
          <SplitBar
            cardTitle="Fixed vs. variable"
            items={detail.analytics.outflow_fixed_variable_split}
            formatMoney={formatMoney}
            colors={["#4f8cff", "#7d67ff"]}
          />
        </div>
      </section>

      <section>
        <div
          className="cashFlowSectionHeading"
          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}
        >
          <div>
            <p className="wealthEyebrow">Merchants</p>
            <h2 className="cashFlowSectionTitle">{merchantsView === "dining" ? "Top dining merchants" : "Top merchants"}</h2>
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
        <div className="card" aria-label={merchantsView === "dining" ? "Top dining merchants chart" : "Top merchants chart"}>
          <MerchantRows items={activeMerchantItems} formatMoney={formatMoney} />
        </div>
      </section>

      <section>
        <div className="cashFlowSectionHeading">
          <p className="wealthEyebrow">Getting worse</p>
          <h2 className="cashFlowSectionTitle">Categories trending up</h2>
        </div>
        <div className="card">
          <DriverRows items={detail.analytics.outflow_category_deltas} formatMoney={formatMoney} />
        </div>
      </section>

      <TransactionListSection
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
        amountTone="bad"
        pageSize={8}
      />
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
  const formatMoney: FormatMoney = (value, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const shellTitle =
    workspaceTab === "income"
      ? "Income"
      : workspaceTab === "expenses"
        ? "Expenses"
        : "Cash Flow Overview";

  const shellSubtitle =
    workspaceTab === "income"
      ? "What funded the month, and how concentrated it was."
      : workspaceTab === "expenses"
        ? "Where the money went, who captured it, and what's getting worse."
        : "What came in, what went out, and how your cash balance moved this month.";

  async function handleSave(transactionId: number, categoryId: number): Promise<boolean> {
    setPendingOverrides((current) => ({ ...current, [transactionId]: true }));
    setOverrideErrors((current) => {
      const next = { ...current };
      delete next[transactionId];
      return next;
    });

    let succeeded = false;
    try {
      await api.categoryOverride({ transaction_id: transactionId, category_id: categoryId });
      const refreshed = await api.cashFlowDetail(month, baseCurrency);
      setDetail(refreshed);
      setOverrideSelections((current) => {
        const next = { ...current };
        delete next[transactionId];
        return next;
      });
      succeeded = true;
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
    return succeeded;
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
        <div className="wealthOverviewLayout">
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
