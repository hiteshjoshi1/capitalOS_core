import { useCallback, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CreditCardTransaction } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import { chartColor } from "../lib/chartColors";
import { computeDueStatus, dueSortValue, formatShortDate } from "../lib/dueStatus";
import type { DueStatus } from "../lib/dueStatus";
import "../App.css";
import MonthBar from "../components/MonthBar";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import FxNote from "../components/FxNote";
import DueStatusPill from "../components/DueStatusPill";
import TrendBarChart from "../components/TrendBarChart";
import StackedBar from "../components/StackedBar";
import { useBaseCurrency } from "../context/CurrencyContext";
import LoadError from "../components/LoadError";
import {
  NOTABLE_THRESHOLD,
  TRANSACTION_FILTERS,
  filterCounts,
  filterTransactions,
  recurringFor,
  recurringIndex,
  type TransactionFilter,
} from "../lib/liabilities";

type UpcomingRow = {
  key: string;
  name: string;
  typeLabel: string;
  dueStatus: DueStatus;
  dueDateLabel: string | null;
  sortValue: number;
};

function cardColor(index: number): string {
  return chartColor(index);
}

function cardGradient(index: number): string {
  const color = cardColor(index);
  return `linear-gradient(135deg, color-mix(in srgb, ${color} 55%, #12141a) 0%, color-mix(in srgb, ${color} 30%, #12141a) 100%)`;
}

function monthLabel(month: string): string {
  return fmt.formatMonth(month);
}

function csvEscape(value: string): string {
  if (/["\n,]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

function transactionsToCsv(rows: CreditCardTransaction[]): string {
  const header = ["Date", "Merchant", "Card", "Category", "Type", "Amount"];
  const lines = rows.map((t) =>
    [
      t.ts.slice(0, 10),
      t.description,
      t.card_name,
      t.resolved_category || t.category || "Uncategorized",
      t.type,
      fmt.formatCsvNumber(Math.abs(t.amount)),
    ]
      .map((cell) => csvEscape(String(cell)))
      .join(","),
  );
  return [header.join(","), ...lines].join("\n");
}

function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export default function LiabilitiesOverview() {
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency] = useBaseCurrency();
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [txFilter, setTxFilter] = useState<TransactionFilter>("all");

  // #148: the account list doesn't depend on month, currency or card filter, so it has
  // its own resource and is no longer refetched on every filter change.
  const analytics = useApiResource(
    resourceKey("creditCardAnalytics", month, baseCurrency, 12, selectedAccountId),
    () => api.creditCardAnalytics(month, baseCurrency, 12, selectedAccountId),
  );
  const accountsRes = useApiResource("accounts", () => api.accounts());
  const data = analytics.data ?? null;
  const accounts = useMemo(() => accountsRes.data ?? [], [accountsRes.data]);

  // The currency the shown numbers are in (the previous one while a switch loads).
  const shownCurrency = data?.base_currency || baseCurrency;
  // #266: totals and summaries in whole units; a single charge with its cents.
  const formatMoney = useCallback(
    (value?: number | null, decimals: number = 0) => fmt.formatMoney(value, shownCurrency, { decimals }),
    [shownCurrency],
  );
  const formatMoneyShort = useCallback((value?: number | null) => fmt.formatMoneyCompact(value, shownCurrency), [shownCurrency]);

  const selectedCard = useMemo(
    () => (selectedAccountId != null ? data?.cards.find((c) => c.account_id === selectedAccountId) : null),
    [data, selectedAccountId],
  );

  // Derived from linked accounts, not a hardcoded flag — activates automatically
  // once loan-linking ships (see tasks/issue-194-loan-account-integration.md).
  const loanAccounts = useMemo(() => accounts.filter((a) => a.account_type === "LOAN"), [accounts]);
  const hasLoans = loanAccounts.length > 0;

  const upcomingRows: UpcomingRow[] = useMemo(() => {
    const cardRows: UpcomingRow[] = (data?.cards ?? []).map((c) => {
      const dueStatus = computeDueStatus({ dueDate: c.due_date });
      return {
        key: `card-${c.account_id}`,
        name: c.card_name,
        typeLabel: "Credit card",
        dueStatus,
        dueDateLabel: formatShortDate(c.due_date),
        sortValue: dueSortValue(dueStatus, c.due_date),
      };
    });
    const loanRows: UpcomingRow[] = hasLoans
      ? loanAccounts.map((l) => {
          const dueStatus = computeDueStatus({ dueDate: null, dueSource: null });
          return {
            key: `loan-${l.id}`,
            name: l.name,
            typeLabel: "Loan payment",
            dueStatus,
            dueDateLabel: null,
            sortValue: dueSortValue(dueStatus, null),
          };
        })
      : [];
    return [...cardRows, ...loanRows].sort((a, b) => a.sortValue - b.sortValue);
  }, [data, hasLoans, loanAccounts]);

  // #266: one transaction list with filters (All / Notable / Recurring / Fees & charges)
  // replaces the Notable, Recurring, Fees and Transactions sections.
  const recurring = useMemo(() => recurringIndex(data?.recurring_payments ?? []), [data]);
  const counts = useMemo(() => filterCounts(data?.transactions ?? [], recurring), [data, recurring]);
  const shownTransactions = useMemo(
    () => filterTransactions(data?.transactions ?? [], txFilter, recurring),
    [data, txFilter, recurring],
  );

  const delta = data ? data.total_spend - data.prior_month_spend : null;
  const largestCategory = data && data.categories.length > 0 ? data.categories[0] : null;
  const trendAriaLabel = `${data?.months ?? 12}-month credit card spend trend${selectedCard ? ` for ${selectedCard.card_name}` : ""}`;

  const pageSubtitle = hasLoans
    ? "Card spend, unusual charges, and loan payments — without unreliable balance estimates."
    : "Monthly spend, unusual charges, and transaction history — without unreliable balance estimates.";

  return (
    <PageShell
      title="Liabilities"
      subtitle={pageSubtitle}
      monthBar={<MonthBar month={month} onMonthChange={setMonth} />}
    >
      {analytics.isLoading ? <div className="card" role="status">Loading…</div> : null}

      {analytics.error ? (
        <LoadError
          title="Couldn't load card spend"
          error={analytics.error}
          onRetry={() => {
            void analytics.reload().catch(() => undefined);
            if (accountsRes.error) void accountsRes.reload().catch(() => undefined);
          }}
        />
      ) : null}

      {data ? (
        <RefreshingRegion busy={analytics.isFetching}>
        {data.cards.length === 0 ? (
          <div className="liabNoLoansBanner">
            <div className="liabNoLoansText">
              <strong>No credit cards linked yet</strong>
              <span className="muted">Add a credit card account to see monthly spend, charges, and trends here.</span>
            </div>
            <a className="btn" href="/accounts/new">
              Add account
            </a>
          </div>
        ) : (
          <div className="wealthOverviewLayout">
            <div className="ccFilterRail" role="group" aria-label="Filter by card">
              <button
                type="button"
                className="ccFilterPill"
                aria-pressed={selectedAccountId === null}
                onClick={() => setSelectedAccountId(null)}
              >
                <i className="ccFilterDot" style={{ background: "var(--accent)" }} aria-hidden="true" />
                All cards
              </button>
              {data.cards.map((card, index) => (
                <button
                  key={card.account_id}
                  type="button"
                  className="ccFilterPill"
                  aria-pressed={selectedAccountId === card.account_id}
                  onClick={() => setSelectedAccountId(card.account_id)}
                >
                  <i className="ccFilterDot" style={{ background: cardColor(index) }} aria-hidden="true" />
                  {card.card_name}
                </button>
              ))}
            </div>

            <FxNote sources={[data]} />
            <section className="ccHeroGrid">
              <HeroMetricCard
                eyebrow={`Spent in ${monthLabel(data.month)}`}
                value={formatMoney(data.total_spend)}
                delta={
                  delta != null
                    ? {
                        abs: delta,
                        currency: shownCurrency,
                        show: "abs",
                        baseline: `vs ${monthLabel(data.prior_month)}`,
                        // More card spend is the bad direction.
                        tone: "inverse",
                      }
                    : null
                }
                insightText={`${data.transaction_count} purchase${data.transaction_count === 1 ? "" : "s"}${
                  selectedCard ? ` on ${selectedCard.card_name}` : ` across ${data.cards.length} card${data.cards.length === 1 ? "" : "s"}`
                }`}
              />
              <article className="card cashFlowKpiCard">
                <p className="wealthEyebrow">Card charges</p>
                <p className={`cashFlowKpiValue${data.charge_total > 0 ? " bad" : ""}`}>{formatMoney(data.charge_total)}</p>
                <p className="muted">Fees, interest and tax — review below</p>
              </article>
              <article className="card cashFlowKpiCard">
                <p className="wealthEyebrow">Largest category</p>
                <p className="cashFlowKpiValue">{largestCategory ? largestCategory.label : "—"}</p>
                <p className="muted">
                  {largestCategory
                    ? `${formatMoney(largestCategory.amount)} · ${fmt.formatPercent(largestCategory.percent)} of purchase spend`
                    : "No purchases yet this month"}
                </p>
              </article>
            </section>

            {data.charges.length > 0 ? (
              <section className="ccChargeAlert">
                <div>
                  <div className="ccChargeAlertTitle">
                    {data.charges.length} card charge{data.charges.length === 1 ? "" : "s"} need attention
                  </div>
                  <div className="ccChargeAlertMeta">Annual fees, finance charges and tax included in this month's spend.</div>
                </div>
                <div className="ccChargeAlertSide">
                  <div className="ccChargeAlertAmount">{formatMoney(data.charge_total)}</div>
                  <button type="button" className="btn" onClick={() => setTxFilter("charges")}>
                    Show charges
                  </button>
                </div>
              </section>
            ) : (
              <section className="card">
                <p className="muted">No card charges this month.</p>
              </section>
            )}

            <section className="ccCardGrid">
              {data.cards.map((card, index) => (
                <article className="ccCardTile" key={card.account_id} style={{ background: cardGradient(index) }}>
                  <div className="ccCardTileHeader">
                    <div>
                      <div className="ccCardTileName">{card.card_name}</div>
                      <span className="ccCardTileIssuer">{card.issuer}</span>
                    </div>
                    <span className="ccCardTileTx">{card.transaction_count} tx</span>
                  </div>
                  <div className="ccCardTileFooter">
                    <div>
                      <div className="ccCardTileSpend">{formatMoney(card.spend)}</div>
                      <div className="ccCardTileSub">spent this month</div>
                    </div>
                    {/* #266: shown only when the issuer gives it; no "not provided" filler. */}
                    {card.available_limit != null && card.available_limit_as_of != null ? (
                      <div className="ccCardTileAvailable">
                        Available credit
                        <strong>{formatMoney(card.available_limit)}</strong>
                        <span>as of {fmt.formatDate(card.available_limit_as_of.slice(0, 10))}</span>
                      </div>
                    ) : null}
                  </div>
                </article>
              ))}
            </section>

            <section>
              <div className="cashFlowSectionHeading">
                <p className="wealthEyebrow">Payment timing</p>
                <h2 className="cashFlowSectionTitle">Upcoming payments</h2>
              </div>
              <div className="card">
                <div className="listRows">
                  {upcomingRows.map((row) => (
                    <div className="listRow liabDueRow" key={row.key}>
                      <div className="listRowMain">
                        <span className="listRowTitle">{row.name}</span>
                        <span className="listRowMeta">{row.typeLabel}</span>
                      </div>
                      <DueStatusPill status={row.dueStatus} dateLabel={row.dueDateLabel} />
                    </div>
                  ))}
                  {upcomingRows.length === 0 && <p className="muted">No upcoming payments.</p>}
                </div>
              </div>
            </section>

            {hasLoans ? (
              <section>
                <div className="cashFlowSectionHeading">
                  <p className="wealthEyebrow">Installment</p>
                  <h2 className="cashFlowSectionTitle">Loans</h2>
                </div>
                <div style={{ display: "grid", gap: 14 }}>
                  {loanAccounts.map((l) => (
                    <div className="card liabLoanRow" key={l.id}>
                      <div className="liabLoanMeta">
                        <strong>{l.name}</strong>
                        <span className="muted" style={{ fontSize: 12 }}>
                          {l.platform || "Lender not set"}
                        </span>
                      </div>
                      <div className="liabLoanBalance">
                        <strong style={{ fontSize: 16 }}>Not synced</strong>
                        <span className="muted" style={{ fontSize: 12 }}>
                          Rate &amp; term pending loan sync
                        </span>
                      </div>
                      <div className="liabLoanNextPayment">
                        <span className="muted" style={{ fontSize: 12 }}>
                          Next payment
                        </span>
                        <strong>Not synced</strong>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ) : (
              <section>
                <div className="liabNoLoansBanner">
                  <div className="liabNoLoansText">
                    <strong style={{ fontSize: 13 }}>No loans linked</strong>
                    <span className="muted" style={{ fontSize: 12 }}>
                      Home, auto, and personal loans will show up here once you connect a lender.
                    </span>
                  </div>
                  <button type="button" disabled className="liabConnectLoanBtn">
                    Connect a loan
                  </button>
                </div>
              </section>
            )}

            <section className="ccGridMain">
              <article className="whCard">
                <div className="whCardHead">
                  <div>
                    <div className="whCardTitle">{data.months}-month spending trend</div>
                    <div className="whCardMeta">
                      {selectedCard ? selectedCard.card_name : "All cards"} · transaction-derived monthly spend, not balance owed
                    </div>
                  </div>
                  <span className="tag">{data.base_currency}</span>
                </div>
                <TrendBarChart
                  points={data.trend.map((point) => ({
                    month: point.month,
                    value: point.spend,
                    displayValue: formatMoneyShort(point.spend),
                  }))}
                  ariaLabel={trendAriaLabel}
                />
              </article>
              <article className="whCard">
                <div className="whCardHead">
                  <div>
                    <div className="whCardTitle">Spend by category</div>
                    <div className="whCardMeta">Selected month and card scope · purchases only</div>
                  </div>
                </div>
                {data.categories.length === 0 ? (
                  <p className="muted">No categorized spend this month.</p>
                ) : (
                  <StackedBar
                    layout="rows"
                    ariaLabel="Spend by category"
                    segments={data.categories.map((cat, index) => ({
                      key: cat.label,
                      label: cat.label,
                      percent: cat.percent * 100,
                      color: cardColor(index),
                      valueLabel: formatMoney(cat.amount),
                    }))}
                  />
                )}
              </article>
            </section>

            <section className="whCard">
              <div className="whCardHead">
                <div>
                  <div className="whCardTitle">Transactions</div>
                  <div className="whCardMeta">
                    {monthLabel(data.month)} · {selectedCard ? selectedCard.card_name : "All cards"} ·{" "}
                    {shownTransactions.length} of {data.transactions.length} entries
                  </div>
                </div>
                <button
                  type="button"
                  className="btn"
                  disabled={shownTransactions.length === 0}
                  onClick={() =>
                    downloadCsv(
                      `credit-card-transactions-${data.month}${txFilter === "all" ? "" : `-${txFilter}`}.csv`,
                      transactionsToCsv(shownTransactions),
                    )
                  }
                >
                  Export CSV
                </button>
              </div>
              <div className="ccFilterRail liabTxFilters" role="group" aria-label="Filter transactions">
                {TRANSACTION_FILTERS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className="ccFilterPill"
                    aria-pressed={txFilter === key}
                    onClick={() => setTxFilter(key)}
                  >
                    {label} <span className="liabTxFilterCount">{counts[key]}</span>
                  </button>
                ))}
              </div>
              <p className="muted liabTxFilterHint">
                {txFilter === "notable"
                  ? `Single purchases over ${formatMoney(NOTABLE_THRESHOLD)}, biggest first.`
                  : txFilter === "recurring"
                    ? "Charged once a month for at least 3 months, at a steady amount (within 10%)."
                    : txFilter === "charges"
                      ? "Annual fees, interest and tax."
                      : "Every entry, newest first."}
              </p>
              {shownTransactions.length === 0 ? (
                <p className="muted">
                  {data.transactions.length === 0
                    ? "No transactions for this scope."
                    : txFilter === "notable"
                      ? "No notable charges this month."
                      : txFilter === "recurring"
                        ? "No recurring payments detected."
                        : "No card charges this month."}
                </p>
              ) : (
                <div className="tableWrap">
                  <table className="table liabTxTable">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Merchant</th>
                        <th>Card</th>
                        <th>Category</th>
                        <th className="right">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shownTransactions.map((tx, index) => {
                        const repeat = recurringFor(tx, recurring);
                        return (
                          <tr key={`${tx.account_id}-${tx.ts}-${index}`}>
                            <td>{fmt.formatDate(tx.ts.slice(0, 10))}</td>
                            <td>
                              <span className="liabTxMerchant">
                                {/* A purchase by its merchant; a fee or interest line by its own text. */}
                                {tx.type === "EXPENSE" ? tx.merchant_counterparty?.trim() || tx.description : tx.description}
                              </span>
                              {repeat ? (
                                <span className="tag liabTxRepeat">
                                  {fmt.formatEnumLabel(repeat.cadence ?? "monthly")} · {repeat.months_present} months
                                </span>
                              ) : null}
                              {tx.type !== "EXPENSE" ? <span className="tag bad">{fmt.formatEnumLabel(tx.type)}</span> : null}
                            </td>
                            <td>{tx.card_name}</td>
                            <td>
                              <span className="tag">{tx.resolved_category || tx.category || "Uncategorized"}</span>
                            </td>
                            <td className={`right${tx.type !== "EXPENSE" ? " bad" : ""}`}>{formatMoney(Math.abs(tx.amount), 2)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
        </RefreshingRegion>
      ) : null}
    </PageShell>
  );
}
