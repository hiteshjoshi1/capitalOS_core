import { useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CategoryTaxonomy, UnmappedTransaction } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import * as fmt from "../lib/format";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";

type CategoryGroup = {
  label: string;
  options: CategoryTaxonomy[];
};

type MerchantGroup = {
  key: string;
  merchant: string;
  transactions: UnmappedTransaction[];
  total: number;
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

function groupByMerchant(transactions: UnmappedTransaction[]): MerchantGroup[] {
  const byMerchant = new Map<string, UnmappedTransaction[]>();
  for (const transaction of transactions) {
    const key = (transaction.merchant_counterparty || "Unknown").trim() || "Unknown";
    const list = byMerchant.get(key) ?? [];
    list.push(transaction);
    byMerchant.set(key, list);
  }
  return Array.from(byMerchant.entries())
    .map(([merchant, txns]) => ({
      key: merchant,
      merchant,
      transactions: txns,
      total: txns.reduce((sum, t) => sum + Math.abs(t.amount), 0),
    }))
    .sort((a, b) => b.total - a.total);
}

export default function CashFlowMapping() {
  const [month, setMonth] = useSelectedMonth();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [groupSelections, setGroupSelections] = useState<Record<string, string>>({});
  const [applying, setApplying] = useState<Record<string, boolean>>({});
  const [applyErrors, setApplyErrors] = useState<Record<string, string>>({});
  // Transactions categorised on this page since the queue loaded (hidden at once).
  const [appliedIds, setAppliedIds] = useState<Set<number>>(() => new Set());

  // #148: categories are shared with Cash Flow (one cached request). The queue does NOT
  // keep the previous month on screen while the next loads: it is a work list, and
  // categorising last month's rows under this month's heading would be confusing.
  const categoriesRes = useApiResource("categories", () => api.categories());
  const unmappedRes = useApiResource(
    resourceKey("unmappedTransactions", month),
    () => api.unmappedTransactions(month),
    { keepPreviousData: false },
  );
  const categories = useMemo(() => categoriesRes.data ?? [], [categoriesRes.data]);
  const transactions = useMemo(
    () => (unmappedRes.data ?? []).filter((t) => !appliedIds.has(t.transaction_id)),
    [unmappedRes.data, appliedIds],
  );
  const error = unmappedRes.error ?? categoriesRes.error;
  const ready = unmappedRes.data != null && categoriesRes.data != null && !error;

  // A new month starts with a clean slate (what the old remount-per-fetch did).
  const [stateMonth, setStateMonth] = useState(month);
  if (stateMonth !== month) {
    setStateMonth(month);
    setExpanded({});
    setGroupSelections({});
    setApplyErrors({});
  }

  const categoryGroups = groupCategories(categories);
  // Queue rows are raw transactions in their own currency (the API doesn't convert
  // them), so each amount is labelled with its own currency, not the base currency.
  const formatMoney = (value: number, currency: string | null | undefined) =>
    fmt.formatMoney(Math.abs(value), currency, { decimals: 2 });
  const groupTotal = (group: MerchantGroup) => {
    const currencies = new Set(group.transactions.map((t) => t.currency));
    return currencies.size === 1 ? formatMoney(group.total, [...currencies][0]) : "mixed currencies";
  };

  const allGroups = useMemo(() => groupByMerchant(transactions), [transactions]);
  const filteredGroups = useMemo(
    () => allGroups.filter((g) => g.merchant.toLowerCase().includes(search.trim().toLowerCase())),
    [allGroups, search],
  );

  async function handleApplyAll(group: MerchantGroup) {
    const selectedValue = groupSelections[group.key] ?? "";
    const categoryId = Number(selectedValue);
    if (!Number.isFinite(categoryId) || categoryId <= 0) {
      return;
    }

    setApplying((current) => ({ ...current, [group.key]: true }));
    setApplyErrors((current) => {
      const next = { ...current };
      delete next[group.key];
      return next;
    });

    try {
      const transactionIds = group.transactions.map((t) => t.transaction_id);
      await api.categoryOverrideBulk({ transaction_ids: transactionIds, category_id: categoryId });
      setAppliedIds((current) => new Set([...current, ...transactionIds]));
    } catch (e: unknown) {
      setApplyErrors((current) => ({
        ...current,
        [group.key]: e instanceof Error ? e.message : "Apply failed. Try again after checking the API state.",
      }));
    } finally {
      setApplying((current) => {
        const next = { ...current };
        delete next[group.key];
        return next;
      });
    }
  }

  return (
    <PageShell
      title="Map Transactions"
      subtitle="Resolve uncategorized transactions — grouped by merchant so you can categorize once, not row by row."
      activeRoute="/cash-flow/map-transactions"
      secondaryNavItem={{ label: "Map Transactions", to: "/cash-flow/map-transactions" }}
      unmappedCount={transactions.length}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <BaseCurrencyPicker />
        </>
      )}
    >
      {!ready && !error && <div className="card">Loading…</div>}

      {error && (
        <div className="card error">
          <div className="cardTitle">Category mapping unavailable</div>
          <pre className="pre">{error.message}</pre>
          <div className="hint">
            Check that the API is running. If category tables are missing, run <code>make db-migrate</code> then <code>make api-rebuild</code>.
          </div>
        </div>
      )}

      {ready && transactions.length === 0 && (
        <div className="card">
          <div className="cardTitle">Unmapped queue</div>
          <div>All transactions mapped for {month}.</div>
        </div>
      )}

      {ready && transactions.length > 0 && (
        <div className="wealthOverviewLayout">
          <div className="card">
            <div className="stockHoldingsHeader">
              <span className="muted">
                {transactions.length} transactions across {allGroups.length} merchants still need a category
              </span>
              <input
                type="text"
                className="input"
                style={{ maxWidth: 240 }}
                placeholder="Search merchant…"
                aria-label="Search merchant"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </div>

          <div className="listRows">
            {filteredGroups.length === 0 ? (
              <div className="card muted">No merchants match "{search}".</div>
            ) : (
              filteredGroups.map((group) => {
                const isExpanded = expanded[group.key] ?? false;
                const selectedValue = groupSelections[group.key] ?? "";
                const canApply = Number.isFinite(Number(selectedValue)) && Number(selectedValue) > 0;
                const isApplying = applying[group.key] ?? false;

                return (
                  <div className="card" key={group.key} style={{ marginBottom: 12 }}>
                    <div className="cashFlowCardHeader">
                      <div>
                        <strong>{group.merchant}</strong>
                        <div className="muted">
                          {group.transactions.length} transactions · {groupTotal(group)}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setExpanded((current) => ({ ...current, [group.key]: !isExpanded }))}
                      >
                        {isExpanded ? "Hide" : "Review"}
                      </button>
                    </div>

                    <div className="cashFlowEditor" style={{ marginTop: 10 }}>
                      <select
                        className="input overrideSelect"
                        aria-label={`Category for ${group.merchant}`}
                        value={selectedValue}
                        disabled={isApplying}
                        onChange={(event) =>
                          setGroupSelections((current) => ({ ...current, [group.key]: event.target.value }))
                        }
                      >
                        <option value="">Select category</option>
                        {categoryGroups.map((cg) => (
                          <optgroup key={cg.label} label={cg.label}>
                            {cg.options.map((category) => (
                              <option key={category.id} value={category.id}>
                                {category.name}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="btn btnPrimary"
                        disabled={!canApply || isApplying}
                        onClick={() => void handleApplyAll(group)}
                      >
                        {isApplying ? "Applying…" : `Apply to all ${group.transactions.length}`}
                      </button>
                    </div>
                    {applyErrors[group.key] ? <div className="overrideError">{applyErrors[group.key]}</div> : null}

                    {isExpanded ? (
                      <div className="listRows" style={{ marginTop: 10 }}>
                        {group.transactions.map((transaction) => (
                          <div className="listRow" key={transaction.transaction_id}>
                            <div className="listRowMain">
                              <span className="listRowTitle">{fmt.formatDate(asDate(transaction.ts))}</span>
                              <span className="listRowMeta">
                                <span>{transaction.account_name}</span>
                                <span>{transaction.raw_category ?? "Uncategorized"}</span>
                              </span>
                            </div>
                            <div className={`listRowValue ${transaction.amount < 0 ? "bad" : "good"}`}>
                              {formatMoney(transaction.amount, transaction.currency)}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}
