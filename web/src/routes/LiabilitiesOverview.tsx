import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { Account, CreditCardDetail, CreditCardTransaction } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import { computeDueStatus, dueSortValue, formatShortDate } from "../lib/dueStatus";
import type { DueStatus } from "../lib/dueStatus";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import DueStatusPill from "../components/DueStatusPill";
import CreditCardWalletTile from "../components/dashboard/CreditCardWalletTile";

type LoadState = "idle" | "loading" | "ready" | "error";

type UpcomingRow = {
  key: string;
  name: string;
  typeLabel: string;
  amountLabel: string;
  dueStatus: DueStatus;
  dueDateLabel: string | null;
  sortValue: number;
};

const CHART_COLORS = [
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

function asDate(ts: string) {
  return ts.slice(0, 10);
}

function categoryDonutGradient(items: Array<{ value: number }>) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  let offset = 0;
  const parts = items.map((item, idx) => {
    const next = total > 0 ? offset + (item.value / total) * 100 : offset;
    const part = `${CHART_COLORS[idx % CHART_COLORS.length]} ${offset.toFixed(2)}% ${next.toFixed(2)}%`;
    offset = next;
    return part;
  });
  if (offset < 100) {
    parts.push(`color-mix(in srgb, var(--line) 65%, transparent 35%) ${offset.toFixed(2)}% 100%`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

function previousMonth(month: string): string {
  const [year, monthIndex] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, monthIndex - 1, 1));
  date.setUTCMonth(date.getUTCMonth() - 1);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

export default function LiabilitiesOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState("");
  const [detail, setDetail] = useState<CreditCardDetail | null>(null);
  const [priorDetail, setPriorDetail] = useState<CreditCardDetail | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState("SGD");
  const [ledgerOpen, setLedgerOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setState("loading");
        const [current, prior, accountList] = await Promise.all([
          api.creditCardTransactions(month, baseCurrency),
          api.creditCardTransactions(previousMonth(month), baseCurrency),
          api.accounts(),
        ]);
        if (cancelled) return;
        setDetail(current);
        setPriorDetail(prior);
        setAccounts(accountList);
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

  const effectiveBaseCurrency = detail?.base_currency || baseCurrency;
  const currencyPrefix = effectiveBaseCurrency === "SGD" ? "S$" : `${effectiveBaseCurrency} `;
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  const cards = useMemo(() => detail?.cards ?? [], [detail]);
  const transactions = useMemo(() => detail?.transactions ?? [], [detail]);
  const expenseTransactions = useMemo(() => transactions.filter((t) => t.type === "EXPENSE"), [transactions]);

  // Derived from linked accounts, not a hardcoded flag — activates automatically
  // once loan-linking ships (see tasks/issue-194-loan-account-integration.md).
  const loanAccounts = useMemo(() => accounts.filter((a) => a.account_type === "LOAN"), [accounts]);
  const hasLoans = loanAccounts.length > 0;

  const totalCardBalance = cards.reduce((sum, c) => sum + (c.current_due ?? 0), 0);
  const totalCardLimit = cards.reduce((sum, c) => sum + (c.credit_limit ?? 0), 0);
  const blendedUtilization = totalCardLimit > 0 ? Math.round((totalCardBalance / totalCardLimit) * 100) : 0;
  // Real loan balances await backend loan integration — see tasks/issue-194-loan-account-integration.md.
  const totalLoanBalance = 0;
  const totalLiabilities = totalCardBalance + (hasLoans ? totalLoanBalance : 0);
  const cardsShare = totalLiabilities > 0 ? Math.round((totalCardBalance / totalLiabilities) * 100) : 100;

  const priorTotal = (priorDetail?.cards ?? []).reduce((sum, c) => sum + (c.current_due ?? 0), 0);
  const delta = totalCardBalance - priorTotal;
  const deltaChip = priorDetail
    ? { text: `${delta >= 0 ? "+" : "-"}${formatMoney(Math.abs(delta))} vs last month`, positive: delta <= 0 }
    : null;

  const upcomingRows: UpcomingRow[] = useMemo(() => {
    const cardRows: UpcomingRow[] = cards.map((c) => {
      const dueStatus = computeDueStatus({ dueDate: c.due_date, dueSource: c.current_due_source });
      return {
        key: `card-${c.account_id}`,
        name: c.card_name,
        typeLabel: "Credit card",
        amountLabel: formatMoney(c.current_due),
        dueStatus,
        dueDateLabel: dueStatus.tone === "not-synced" ? null : formatShortDate(c.due_date),
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
            amountLabel: "—",
            dueStatus,
            dueDateLabel: null,
            sortValue: dueSortValue(dueStatus, null),
          };
        })
      : [];
    return [...cardRows, ...loanRows].sort((a, b) => a.sortValue - b.sortValue);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, hasLoans, loanAccounts, currencyPrefix]);

  const categoryRows = useMemo(() => {
    const totals = new Map<string, number>();
    for (const t of expenseTransactions) {
      const label = t.resolved_category?.trim() || "Uncategorized";
      totals.set(label, (totals.get(label) ?? 0) + Math.abs(t.amount));
    }
    const totalSpend = Array.from(totals.values()).reduce((sum, v) => sum + v, 0);
    return Array.from(totals.entries())
      .map(([label, value]) => ({ label, value, percent: totalSpend > 0 ? Math.round((value / totalSpend) * 100) : 0 }))
      .sort((a, b) => b.value - a.value);
  }, [expenseTransactions]);

  const notableRows = useMemo(
    () =>
      [...expenseTransactions]
        .filter((t) => Math.abs(t.amount) > NOTABLE_THRESHOLD)
        .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount)),
    [expenseTransactions],
  );

  const ledgerRows = useMemo(
    () => [...transactions].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()),
    [transactions],
  );

  function renderTransactionRow(tx: CreditCardTransaction, key: string) {
    // Purchases (money spent on the card) are the normal case and shouldn't read as
    // alarming; only money paid out to the card issuer (settling the balance) is red.
    const isPaymentToIssuer = tx.amount > 0;
    return (
      <div className="listRow liabDueRow" key={key}>
        <div className="listRowMain">
          <span className="listRowTitle">{tx.merchant_counterparty || tx.description}</span>
          <span className="listRowMeta">
            {asDate(tx.ts)} · {tx.card_name}
          </span>
        </div>
        <span className="tag">{tx.resolved_category?.trim() || "Uncategorized"}</span>
        <span className={`listRowValue${isPaymentToIssuer ? " bad" : ""}`}>{formatMoney(tx.amount, 2)}</span>
      </div>
    );
  }

  const pageSubtitle = hasLoans
    ? "Revolving and installment debt across every account, in one place."
    : "Your revolving balances, all in one place.";

  return (
    <PageShell
      title="Liabilities"
      subtitle={pageSubtitle}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="coPillBtn">
            <span aria-hidden="true">{baseCurrency}</span>
            <select
              className="coPillBtnInput"
              aria-label="Base currency"
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
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
      {state === "loading" && <div className="card">Loading...</div>}
      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <div className="wealthOverviewLayout">
          <HeroMetricCard
            eyebrow={hasLoans ? "Total liabilities" : "Credit card balance"}
            value={formatMoney(totalLiabilities)}
            deltaChip={deltaChip}
            insightText={
              hasLoans
                ? `${formatMoney(totalCardBalance)} revolving across ${cards.length} card${cards.length === 1 ? "" : "s"} · ${formatMoney(totalLoanBalance)} installment across ${loanAccounts.length} loan${loanAccounts.length === 1 ? "" : "s"}.`
                : `${cards.length} card${cards.length === 1 ? "" : "s"} linked · blended utilization ${blendedUtilization}%.`
            }
          >
            {hasLoans ? (
              <div className="coHeroLegendRow">
                <span className="coHeroLegendItem">
                  <i className="coHeroLegendDot" style={{ background: "#4f8cff" }} />
                  Revolving (cards) — {cardsShare}%
                </span>
                <span className="coHeroLegendItem">
                  <i className="coHeroLegendDot" style={{ background: "#7d67ff" }} />
                  Installment (loans) — {100 - cardsShare}%
                </span>
              </div>
            ) : null}
          </HeroMetricCard>

          <section>
            <div
              className="cashFlowSectionHeading"
              style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}
            >
              <div>
                <p className="wealthEyebrow">Your cards</p>
                <h2 className="cashFlowSectionTitle">Wallet</h2>
              </div>
              <span className="muted">
                {formatMoney(detail?.total_spend)} spent this month across {cards.length} card{cards.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="ccWalletRow">
              {cards.map((c, idx) => {
                const pct = Math.round((c.utilization ?? (c.credit_limit ? c.current_due / c.credit_limit : 0)) * 100);
                const dueStatus = computeDueStatus({ dueDate: c.due_date, dueSource: c.current_due_source });
                return (
                  <CreditCardWalletTile
                    key={c.account_id}
                    variant="wallet"
                    name={c.card_name}
                    meta={c.issuer}
                    balanceLabel={formatMoney(c.current_due)}
                    limitLabel={formatMoney(c.credit_limit)}
                    utilPercent={pct}
                    dueStatus={dueStatus}
                    gradientIndex={idx}
                  />
                );
              })}
              {cards.length === 0 && <p className="muted">No credit cards linked yet.</p>}
            </div>
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
                    <span className="listRowValue">{row.amountLabel}</span>
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

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Composition</p>
              <h2 className="cashFlowSectionTitle">Spend by category</h2>
            </div>
            {categoryRows.length > 0 ? (
              <div className="card cashFlowDonutLayout" style={{ padding: 28 }} aria-label="Spend by category">
                <div className="cashFlowDonutChart" style={{ background: categoryDonutGradient(categoryRows) }}>
                  <div className="cashFlowDonutCenter">
                    <span className="label">Total</span>
                    <strong>{formatMoney(detail?.total_spend)}</strong>
                  </div>
                </div>
                <div className="cashFlowLegendList">
                  {categoryRows.map((item, idx) => (
                    <div className="cashFlowLegendRow" key={item.label}>
                      <span className="cashFlowLegendLabel">
                        <i style={{ background: CHART_COLORS[idx % CHART_COLORS.length] }} />
                        <span className="cashFlowLegendText">{item.label}</span>
                      </span>
                      <span className="muted">
                        {formatMoney(item.value)} <strong>{item.percent}%</strong>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="card muted">No categorized spend for this month.</div>
            )}
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
                {notableRows.map((tx, idx) => renderTransactionRow(tx, `notable-${idx}`))}
                {notableRows.length === 0 && <p className="muted">No notable charges this month.</p>}
              </div>
            </div>
          </section>

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Subscriptions</p>
              <h2 className="cashFlowSectionTitle">Recurring charges</h2>
            </div>
            <div className="card">
              <div className="listRows">
                {detail?.recurring_payments.map((payment) => (
                  <div className="listRow" key={`${payment.account_id}-${payment.merchant_counterparty}`}>
                    <span className="listRowTitle">{payment.merchant_counterparty}</span>
                    <span className="listRowMeta">
                      {payment.card_name} · {payment.months_present} months
                    </span>
                    <span className="listRowValue">{formatMoney(payment.current_month_amount, 2)}</span>
                  </div>
                ))}
                {detail && detail.recurring_payments.length === 0 && (
                  <p className="muted">No recurring payments detected in the last 3 months.</p>
                )}
              </div>
            </div>
          </section>

          <section>
            <div
              className="cashFlowSectionHeading"
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}
            >
              <div>
                <p className="wealthEyebrow">Audit trail</p>
                <h2 className="cashFlowSectionTitle">All transactions</h2>
              </div>
              <button type="button" className="ccLedgerToggle" onClick={() => setLedgerOpen((open) => !open)}>
                {ledgerOpen ? "Show less" : `Show all ${ledgerRows.length} transactions`}
              </button>
            </div>
            {ledgerOpen && (
              <div className="card">
                <div className="listRows">
                  {ledgerRows.map((tx, idx) => renderTransactionRow(tx, `ledger-${idx}`))}
                  {ledgerRows.length === 0 && <p className="muted">No credit card transactions for this month.</p>}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </PageShell>
  );
}
