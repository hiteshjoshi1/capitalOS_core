import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CashFlowDetail, CashFlowTransaction, CategoryTaxonomy } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

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
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
  onSelectionChange: (transactionId: number, value: string) => void;
  onSave: (transactionId: number, categoryId: number) => Promise<void>;
};

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

function TransactionTable({
  title,
  emptyMessage,
  transactions,
  categoryGroups,
  overrideSelections,
  pendingOverrides,
  overrideErrors,
  formatMoney,
  onSelectionChange,
  onSave,
}: TransactionTableProps) {
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
    </div>
  );
}

export default function CashFlowDetailRoute() {
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
        setCategories(taxonomy);
        setDetail(data);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const categoryGroups = groupCategories(categories);
  const effectiveBaseCurrency = detail?.base_currency || baseCurrency;
  const currencyPrefix = effectiveBaseCurrency === "SGD" ? "S$" : effectiveBaseCurrency;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

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
      title="Cash Flow"
      subtitle="Verify how income, expenses, and net were derived for the selected month."
      activeRoute="/cash-flow"
      secondaryNavItem={{ label: "Cash Flow", to: "/cash-flow" }}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
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

      {state === "ready" && detail && (
        <>
          <section className="grid g-mid">
            <div className="card">
              <h2>Net Cash Flow</h2>
              <div className={`big small ${detail.net < 0 ? "bad" : "good"}`}>{formatMoney(detail.net)}</div>
              <div className="muted">{detail.month}</div>
            </div>

            <div className="card">
              <h2>Income</h2>
              <div className="big small good">{formatMoney(detail.income_total)}</div>
              <div className="muted">
                {detail.income.transaction_count} transactions | types {detail.income.included_types.join(", ")}
              </div>
            </div>

            <div className="card">
              <h2>Expenses</h2>
              <div className="big small bad">{formatMoney(detail.expense_total)}</div>
              <div className="muted">
                {detail.expenses.transaction_count} transactions | types {detail.expenses.included_types.join(", ")}
              </div>
            </div>
          </section>

          <section className="grid" style={{ marginTop: 14 }}>
            <div className="card cashFlowExplain">
              <h2>How this was calculated</h2>
              <p className="muted cashFlowFormula">
                {detail.calculation}
              </p>
              <p>
                Net = {formatMoney(detail.income_total, 2)} - {formatMoney(detail.expense_total, 2)} = {formatMoney(detail.net, 2)}
              </p>
              <p className="muted">
                Savings rate: {detail.savings_rate == null ? "—" : `${(detail.savings_rate * 100).toFixed(1)}%`}
              </p>
              <p className="muted cashFlowHint">
                To correct a row here: choose a category in the table and click Save.
              </p>
              <p className="muted cashFlowHint">
                Rows saved to a Transfer category are excluded from income, expenses, and net as soon as this page refreshes.
              </p>
              <p className="muted cashFlowHint">
                Other category edits keep the row in its current income or expense bucket and update the label only.
              </p>
            </div>
          </section>

          <section className="grid g-mid" style={{ marginTop: 14 }}>
            <TransactionTable
              title={`Income transactions (${detail.income.transaction_count})`}
              emptyMessage={`No income transactions for ${detail.month}.`}
              transactions={detail.income.transactions}
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
            <TransactionTable
              title={`Expense transactions (${detail.expenses.transaction_count})`}
              emptyMessage={`No expense transactions for ${detail.month}.`}
              transactions={detail.expenses.transactions}
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
          </section>
        </>
      )}
    </PageShell>
  );
}
