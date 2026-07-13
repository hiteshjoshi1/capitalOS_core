import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Account, CreditCardAnalytics, CreditCardTransaction } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import { computeDueStatus, dueSortValue, formatShortDate } from "../lib/dueStatus";
import type { DueStatus } from "../lib/dueStatus";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import DueStatusPill from "../components/DueStatusPill";
import TrendBarChart from "../components/TrendBarChart";
import StackedBar from "../components/StackedBar";

type LoadState = "idle" | "loading" | "ready" | "error";

type UpcomingRow = {
  key: string;
  name: string;
  typeLabel: string;
  dueStatus: DueStatus;
  dueDateLabel: string | null;
  sortValue: number;
};

const CARD_COLORS = [
  "#4f8cff",
  "#1fb981",
  "#f59f43",
  "#7d67ff",
  "#ef6ca8",
  "#2ebac6",
  "#8f9db2",
  "#b7a08a",
];

const NOTABLE_THRESHOLD = 50;

function cardColor(index: number): string {
  return CARD_COLORS[index % CARD_COLORS.length];
}

function cardGradient(index: number): string {
  const color = cardColor(index);
  return `linear-gradient(135deg, color-mix(in srgb, ${color} 55%, #12141a) 0%, color-mix(in srgb, ${color} 30%, #12141a) 100%)`;
}

function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  const year = Number(y);
  const mon = Number(m);
  if (!Number.isFinite(year) || !Number.isFinite(mon)) return month;
  return new Date(year, mon - 1, 1).toLocaleString("en", { month: "long", year: "numeric" });
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
      Math.abs(t.amount).toFixed(2),
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
  const [baseCurrency, setBaseCurrency] = useState("SGD");
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);

  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState("");
  const [data, setData] = useState<CreditCardAnalytics | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);

  const fetchAll = useCallback(async () => {
    setState("loading");
    try {
      const [analytics, accountList] = await Promise.all([
        api.creditCardAnalytics(month, baseCurrency, 12, selectedAccountId),
        api.accounts(),
      ]);
      setData(analytics);
      setAccounts(accountList);
      setState("ready");
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : String(error));
      setState("error");
    }
  }, [month, baseCurrency, selectedAccountId]);

  useEffect(() => {
    void (async () => {
      void fetchAll();
    })();
  }, [fetchAll]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : baseCurrency;
  const formatMoney = useCallback(
    (value?: number | null, maximumFractionDigits = 0) =>
      value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`,
    [currencyPrefix],
  );
  const formatMoneyShort = useCallback(
    (value?: number | null) => {
      if (value == null) return "—";
      const abs = Math.abs(value);
      if (abs >= 1_000_000) return `${currencyPrefix} ${(abs / 1_000_000).toFixed(1)}M`;
      if (abs >= 1_000) return `${currencyPrefix} ${(abs / 1_000).toFixed(0)}K`;
      return `${currencyPrefix} ${abs.toFixed(0)}`;
    },
    [currencyPrefix],
  );

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

  const notableRows = useMemo(
    () =>
      (data?.transactions ?? [])
        .filter((t) => t.type === "EXPENSE" && Math.abs(t.amount) > NOTABLE_THRESHOLD)
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount)),
    [data],
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
      headerActions={
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
      }
    >
      {state === "loading" || state === "idle" ? <div className="card">Loading…</div> : null}

      {state === "error" ? (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
          <button type="button" className="btn" onClick={() => void fetchAll()}>
            Retry
          </button>
        </div>
      ) : null}

      {state === "ready" && data ? (
        data.cards.length === 0 ? (
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

            <section className="ccHeroGrid">
              <HeroMetricCard
                eyebrow={`Spent in ${monthLabel(data.month)}`}
                value={formatMoney(data.total_spend, 2)}
                deltaChip={
                  delta != null
                    ? {
                        text: `${delta >= 0 ? "↑" : "↓"} ${formatMoney(Math.abs(delta))} vs ${monthLabel(data.prior_month)}`,
                        positive: delta <= 0,
                      }
                    : null
                }
                insightText={`${data.transaction_count} purchase${data.transaction_count === 1 ? "" : "s"}${
                  selectedCard ? ` on ${selectedCard.card_name}` : ` across ${data.cards.length} card${data.cards.length === 1 ? "" : "s"}`
                }`}
              />
              <article className="card cashFlowKpiCard">
                <p className="wealthEyebrow">Card charges</p>
                <p className={`cashFlowKpiValue${data.charge_total > 0 ? " bad" : ""}`}>{formatMoney(data.charge_total, 2)}</p>
                <p className="muted">Fees, interest and tax — review below</p>
              </article>
              <article className="card cashFlowKpiCard">
                <p className="wealthEyebrow">Largest category</p>
                <p className="cashFlowKpiValue">{largestCategory ? largestCategory.label : "—"}</p>
                <p className="muted">
                  {largestCategory
                    ? `${formatMoney(largestCategory.amount)} · ${(largestCategory.percent * 100).toFixed(1)}% of purchase spend`
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
                <div className="ccChargeAlertAmount">{formatMoney(data.charge_total, 2)}</div>
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
                      <div className="ccCardTileSpend">{formatMoney(card.spend, 2)}</div>
                      <div className="ccCardTileSub">spent this month</div>
                    </div>
                    <div className="ccCardTileAvailable">
                      Available credit
                      {card.available_limit != null && card.available_limit_as_of != null ? (
                        <>
                          <strong>{formatMoney(card.available_limit, 2)}</strong>
                          <span>as of {card.available_limit_as_of.slice(0, 10)}</span>
                        </>
                      ) : (
                        <strong>Not provided by issuer</strong>
                      )}
                    </div>
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

            <section>
              <div
                className="cashFlowSectionHeading"
                style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}
              >
                <div>
                  <p className="wealthEyebrow">Worth a look</p>
                  <h2 className="cashFlowSectionTitle">Notable charges</h2>
                </div>
                <span className="muted">Single charges over {formatMoney(NOTABLE_THRESHOLD)}</span>
              </div>
              <div className="card">
                <div className="listRows">
                  {notableRows.map((tx, idx) => (
                    <div className="listRow liabDueRow" key={`notable-${idx}`}>
                      <div className="listRowMain">
                        <span className="listRowTitle">{tx.merchant_counterparty || tx.description}</span>
                        <span className="listRowMeta">
                          {tx.ts.slice(0, 10)} · {tx.card_name}
                        </span>
                      </div>
                      <span className="tag">{tx.resolved_category?.trim() || "Uncategorized"}</span>
                      <span className="listRowValue">{formatMoney(Math.abs(tx.amount), 2)}</span>
                    </div>
                  ))}
                  {notableRows.length === 0 && <p className="muted">No notable charges this month.</p>}
                </div>
              </div>
            </section>

            <section className="ccChargesAndLedger">
              <article className="whCard">
                <div className="whCardHead">
                  <div>
                    <div className="whCardTitle">Fees &amp; finance charges</div>
                    <div className="whCardMeta">Always visible when present</div>
                  </div>
                  {data.charges.length > 0 ? <span className="tag bad">{data.charges.length} items</span> : null}
                </div>
                {data.charges.length === 0 ? (
                  <p className="muted">No card charges this month.</p>
                ) : (
                  <div className="listRows">
                    {data.charges.map((charge, index) => (
                      <div className="listRow" key={`${charge.account_id}-${charge.ts}-${index}`}>
                        <div className="listRowMain">
                          <div className="listRowTitle">{charge.description}</div>
                          <div className="listRowMeta">
                            <span className="tag">{charge.type}</span>
                            {charge.card_name} · {charge.ts.slice(0, 10)}
                          </div>
                        </div>
                        <div className="listRowValue bad">{formatMoney(Math.abs(charge.amount), 2)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </article>

              <article className="whCard">
                <div className="whCardHead">
                  <div>
                    <div className="whCardTitle">Recurring charges</div>
                    <div className="whCardMeta">Subscriptions detected from 3 stable months</div>
                  </div>
                </div>
                {data.recurring_payments.length === 0 ? (
                  <p className="muted">No recurring payments detected in the last 3 months.</p>
                ) : (
                  <div className="listRows">
                    {data.recurring_payments.map((payment) => (
                      <div className="listRow" key={`${payment.account_id}-${payment.merchant_counterparty}`}>
                        <span className="listRowTitle">{payment.merchant_counterparty}</span>
                        <span className="listRowMeta">
                          {payment.card_name} · {payment.months_present} months
                        </span>
                        <span className="listRowValue">{formatMoney(payment.current_month_amount, 2)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </article>
            </section>

            <section className="whCard">
              <div className="whCardHead">
                <div>
                  <div className="whCardTitle">Transactions</div>
                  <div className="whCardMeta">
                    {monthLabel(data.month)} · {selectedCard ? selectedCard.card_name : "All cards"} · {data.transactions.length}{" "}
                    entries
                  </div>
                </div>
                <button
                  type="button"
                  className="btn"
                  disabled={data.transactions.length === 0}
                  onClick={() => downloadCsv(`credit-card-transactions-${data.month}.csv`, transactionsToCsv(data.transactions))}
                >
                  Export CSV
                </button>
              </div>
              {data.transactions.length === 0 ? (
                <p className="muted">No transactions for this scope.</p>
              ) : (
                <div className="tableWrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Merchant</th>
                        <th>Card</th>
                        <th>Category</th>
                        <th>Type</th>
                        <th className="right">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.transactions.map((tx, index) => (
                        <tr key={`${tx.account_id}-${tx.ts}-${index}`}>
                          <td>{tx.ts.slice(0, 10)}</td>
                          <td>{tx.description}</td>
                          <td>{tx.card_name}</td>
                          <td>
                            <span className="tag">{tx.resolved_category || tx.category || "Uncategorized"}</span>
                          </td>
                          <td>{tx.type}</td>
                          <td className={`right${tx.type !== "EXPENSE" ? " bad" : ""}`}>{formatMoney(Math.abs(tx.amount), 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )
      ) : null}
    </PageShell>
  );
}
