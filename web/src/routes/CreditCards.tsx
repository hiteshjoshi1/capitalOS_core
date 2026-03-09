import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { CreditCardDetail } from "../lib/api";
import "../App.css";

type LoadState = "idle" | "loading" | "ready" | "error";

function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function asDate(ts: string) {
  return ts.slice(0, 10);
}

export default function CreditCards() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [detail, setDetail] = useState<CreditCardDetail | null>(null);
  const [month, setMonth] = useState<string>(currentMonthYYYYMM());
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const data = await api.creditCardTransactions(month, baseCurrency);
        setDetail(data);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const effectiveBaseCurrency = detail?.base_currency || baseCurrency;
  const currencyPrefix = effectiveBaseCurrency === "SGD" ? "S$" : `${effectiveBaseCurrency} `;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "-" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  return (
    <div className="wrap">
      <header className="header">
        <div className="titleBlock">
          <div className="title">Credit Cards</div>
          <div className="subtitle">Per-card money-out breakdown, top purchases, and recurring payments.</div>
        </div>
        <div className="pillRow">
          <Link className="pill" to="/">Dashboard</Link>
          <Link className="pill" to="/cash">Cash</Link>
          <Link className="pill" to="/holdings">Stock Holdings</Link>
          <label className="pill">
            <span>Base</span>
            <select className="monthInput" value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value)}>
              <option value="SGD">SGD</option>
              <option value="USD">USD</option>
              <option value="HKD">HKD</option>
              <option value="INR">INR</option>
            </select>
          </label>
          <label className="pill monthControl">
            <span>Month</span>
            <input className="monthInput" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </label>
        </div>
      </header>

      {state === "loading" && <div className="card">Loading...</div>}
      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <>
          <section className="grid g-mid">
            <div className="card">
              <h2>Card Breakdown</h2>
              <div className="big small">{formatMoney(detail?.total_spend)}</div>
              <div className="muted">Configured cards: {detail?.cards.length ?? 0}</div>

              {detail && detail.cards.length > 0 ? (
                <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
                  {detail.cards.map((card) => {
                    const utilizationPct = Math.max(0, Math.min(100, (card.utilization ?? 0) * 100));
                    return (
                      <details key={card.account_id} className="mini" open>
                        <summary style={{ cursor: "pointer" }}>
                          {card.card_name} ({card.issuer}) - {formatMoney(card.current_due)}
                        </summary>
                        <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                          Utilization: {card.utilization == null ? "-" : `${utilizationPct.toFixed(1)}%`} of {formatMoney(card.credit_limit)}
                        </div>
                        <div className="bar">
                          <span style={{ width: `${utilizationPct}%`, background: "var(--accent)" }}></span>
                        </div>
                        <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                          Statement day {card.statement_day}, due day {card.due_day}, due date {card.due_date}
                        </div>
                      </details>
                    );
                  })}
                </div>
              ) : (
                <div className="hint">No credit card transactions for this month.</div>
              )}
            </div>

            <div className="card">
              <h2>Top Purchases</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Description</th>
                    <th>Card</th>
                    <th className="right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {detail?.top_purchases.map((purchase) => (
                    <tr key={`${purchase.account_id}-${purchase.ts}-${purchase.description}`}>
                      <td>{asDate(purchase.ts)}</td>
                      <td>{purchase.description}</td>
                      <td className="muted">{purchase.card_name}</td>
                      <td className="right bad">{formatMoney(purchase.amount, 2)}</td>
                    </tr>
                  ))}
                  {detail && detail.top_purchases.length === 0 && (
                    <tr>
                      <td className="muted" colSpan={4}>No purchases for this month.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="card">
              <h2>Recurring Payments</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Merchant</th>
                    <th>Card</th>
                    <th className="right">Months</th>
                    <th className="right">This month</th>
                  </tr>
                </thead>
                <tbody>
                  {detail?.recurring_payments.map((payment) => (
                    <tr key={`${payment.account_id}-${payment.merchant_counterparty}`}>
                      <td>{payment.merchant_counterparty}</td>
                      <td className="muted">{payment.card_name}</td>
                      <td className="right">{payment.months_present}</td>
                      <td className="right bad">{formatMoney(-payment.current_month_amount, 2)}</td>
                    </tr>
                  ))}
                  {detail && detail.recurring_payments.length === 0 && (
                    <tr>
                      <td className="muted" colSpan={4}>No recurring payments detected in the last 3 months.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="grid" style={{ marginTop: 14 }}>
            <div className="card">
              <h2>All Transactions</h2>
              <div style={{ maxHeight: 340, overflow: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Description</th>
                      <th>Card</th>
                      <th>Type</th>
                      <th>Category</th>
                      <th className="right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail?.transactions.map((tx) => (
                      <tr key={`${tx.account_id}-${tx.ts}-${tx.description}-${tx.amount}`}>
                        <td>{asDate(tx.ts)}</td>
                        <td>{tx.description}</td>
                        <td className="muted">{tx.card_name}</td>
                        <td>{tx.type}</td>
                        <td>{tx.category ?? "-"}</td>
                        <td className={`right ${tx.amount < 0 ? "bad" : "good"}`}>{formatMoney(tx.amount, 2)}</td>
                      </tr>
                    ))}
                    {detail && detail.transactions.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={6}>No credit card transactions for this month.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
