import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CategoryTaxonomy, UnmappedTransaction } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

type CategoryGroup = {
  label: string;
  options: CategoryTaxonomy[];
};

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

export default function CashFlowMapping() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [categories, setCategories] = useState<CategoryTaxonomy[]>([]);
  const [transactions, setTransactions] = useState<UnmappedTransaction[]>([]);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [pendingOverrides, setPendingOverrides] = useState<Record<number, boolean>>({});
  const [overrideErrors, setOverrideErrors] = useState<Record<number, string>>({});
  const [overrideSelections, setOverrideSelections] = useState<Record<number, string>>({});

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        setErr("");
        setOverrideErrors({});
        setPendingOverrides({});
        setOverrideSelections({});
        const [taxonomy, unmapped] = await Promise.all([
          api.categories(),
          api.unmappedTransactions(month),
        ]);
        setCategories(taxonomy);
        setTransactions(unmapped);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month]);

  const categoryGroups = groupCategories(categories);

  async function handleOverride(transactionId: number, categoryId: number) {
    setPendingOverrides((current) => ({ ...current, [transactionId]: true }));
    setOverrideErrors((current) => {
      const next = { ...current };
      delete next[transactionId];
      return next;
    });

    try {
      await api.categoryOverride({ transaction_id: transactionId, category_id: categoryId });
      setTransactions((current) => current.filter((transaction) => transaction.transaction_id !== transactionId));
    } catch (e: unknown) {
      setOverrideSelections((current) => ({ ...current, [transactionId]: "" }));
      setOverrideErrors((current) => ({
        ...current,
        [transactionId]:
          e instanceof Error ? e.message : "Override failed. Try again after checking the API state.",
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
      title="Map Transactions"
      subtitle="Audit transaction evidence, resolve uncategorized rows, and apply category overrides."
      activeRoute="/cash-flow/map-transactions"
      secondaryNavItem={{ label: "Map Transactions", to: "/cash-flow/map-transactions" }}
      unmappedCount={transactions.length}
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
          <div className="cardTitle">Category mapping unavailable</div>
          <pre className="pre">{err}</pre>
          <div className="hint">
            Check that the API is running. If category tables are missing, run <code>make db-migrate</code> then <code>make api-rebuild</code>.
          </div>
        </div>
      )}

      {state === "ready" && transactions.length === 0 && (
        <div className="card">
          <div className="cardTitle">Unmapped queue</div>
          <div>All transactions mapped for {month}.</div>
        </div>
      )}

      {state === "ready" && transactions.length > 0 && (
        <div className="card">
          <div className="cardTitle">Unmapped queue</div>
          <div className="hint">Apply a category override to remove a transaction from the current month queue.</div>
          <div className="mappingTableWrap">
            <table className="table mappingTable">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Account</th>
                  <th>Merchant</th>
                  <th className="right">Amount</th>
                  <th>Currency</th>
                  <th>Type</th>
                  <th>Raw Category</th>
                  <th>Override</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((transaction) => (
                  <tr
                    key={transaction.transaction_id}
                    className={`mappingRow${pendingOverrides[transaction.transaction_id] ? " isPending" : ""}`}
                  >
                    <td>{asDate(transaction.ts)}</td>
                    <td>{transaction.account_name}</td>
                    <td>{transaction.merchant_counterparty ?? "—"}</td>
                    <td className={`right ${transaction.amount < 0 ? "bad" : "good"}`}>
                      {transaction.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </td>
                    <td>{transaction.currency}</td>
                    <td>{transaction.type}</td>
                    <td>{transaction.raw_category ?? "—"}</td>
                    <td>
                      <select
                        className="input overrideSelect"
                        aria-label={`Override category for transaction ${transaction.transaction_id}`}
                        value={overrideSelections[transaction.transaction_id] ?? ""}
                        disabled={pendingOverrides[transaction.transaction_id]}
                        onChange={(event) => {
                          const nextValue = event.target.value;
                          setOverrideSelections((current) => ({
                            ...current,
                            [transaction.transaction_id]: nextValue,
                          }));
                          const categoryId = Number(nextValue);
                          if (!Number.isFinite(categoryId) || categoryId <= 0) {
                            return;
                          }
                          void handleOverride(transaction.transaction_id, categoryId);
                        }}
                      >
                        <option value="">
                          {pendingOverrides[transaction.transaction_id] ? "Saving..." : "Select category"}
                        </option>
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
                      {overrideErrors[transaction.transaction_id] ? (
                        <div className="overrideError">{overrideErrors[transaction.transaction_id]}</div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </PageShell>
  );
}
