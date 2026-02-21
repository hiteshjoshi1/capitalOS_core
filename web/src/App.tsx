import { useEffect, useState } from "react";
import { api } from "./lib/api";
import type { DashboardSummary, PlatformAllocation, SpendingSummary, CreditCardSummary } from "./lib/api";
import { Link } from "react-router-dom";
import "./App.css";

type LoadState = "idle" | "loading" | "ready" | "error";

function currentMonthYYYYMM() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}


export default function App() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [health, setHealth] = useState<string>("(unknown)");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [platformAllocation, setPlatformAllocation] = useState<PlatformAllocation | null>(null);
  const [spendingSummary, setSpendingSummary] = useState<SpendingSummary | null>(null);
  const [creditCardSummary, setCreditCardSummary] = useState<CreditCardSummary | null>(null);
  const [month, setMonth] = useState<string>(currentMonthYYYYMM());
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  const mom = summary?.net_worth_change?.vs_prev_month;
  const yoy = summary?.net_worth_change?.vs_prev_year;


  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        //hardcode
        const [h, s, pa, ss, cc] = await Promise.all([
          api.health(),
          api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
          api.platformAllocation(month, baseCurrency),
          api.spendingSummary(month, baseCurrency),
          api.creditCardSummary(month, baseCurrency),
        ]);
        setHealth(h.status);
        setState("ready");
        setSummary(s);
        setPlatformAllocation(pa);
        setSpendingSummary(ss);
        setCreditCardSummary(cc);
      } catch (e: any) {
        setErr(e?.message ?? String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const selectedBaseCurrency =
    baseCurrency ||
    summary?.base_currency ||
    spendingSummary?.base_currency ||
    creditCardSummary?.base_currency ||
    "SGD";
  const currencyPrefix = selectedBaseCurrency === "SGD" ? "S$" : `${selectedBaseCurrency} `;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  return (
    <div className="wrap">
      <header className="header">
        <div className="titleBlock">
          <div className="title">CapitalOS — Dashboard</div>
          <div className="subtitle">
            Local-first personal finance control plane. Numbers below are placeholders until ingestion is wired end-to-end.
          </div>
        </div>

        <div className="pillRow">
          <Link className="pill" to="/">Dashboard</Link>
          <Link className="pill" to="/ingest">Ingest</Link>
          <span className="pill">API: {health}</span>
          <span className="pill">As of: {summary?.net_worth_as_of ?? "—"}</span>
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
              value={selectedBaseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
            >
              <option value="SGD">SGD</option>
              <option value="USD">USD</option>
              <option value="HKD">HKD</option>
              <option value="INR">INR</option>
            </select>
          </label>
          <label className="pill monthControl">
            <span>Month</span>
            <input
              className="monthInput"
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            />
          </label>
        </div>
      </header>

      {state === "loading" && <div className="card">Loading…</div>}

      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
          <div className="hint">
            Check: API running on <code>http://localhost:8000</code> and CORS env set.
          </div>
        </div>
      )}

      {state === "ready" && (
        <>
          <section className="grid g-top">
            <div className="card netWorthCard">
              <h2>Net Worth</h2>
              <div className="big">{formatMoney(summary?.net_worth.total)}</div>

              <div className="kpirow">
                <div className="kpi">
                  <div className="label">Cash & Cash Eq</div>
                  <div className="val">{formatMoney(summary?.net_worth.cash)}</div>
                  <div className="delta">MoM <span className="good">+2.1%</span></div>
                </div>
                <div className="kpi">
                  <div className="label">Stocks / Funds</div>
                  <div className="val">{formatMoney(summary?.net_worth.stocks_funds)}</div>
                  <div className="delta">MoM <span className="good">+1.3%</span></div>
                </div>
                <div className="kpi">
                  <div className="label">Crypto</div>
                  <div className="val">{formatMoney(summary?.net_worth.crypto)}</div>
                  <div className="delta">MoM <span className="bad">-4.8%</span></div>
                </div>
                <div className="kpi">
                  <div className="label">Debt (Loans)</div>
                  <div className="val">{formatMoney(summary?.net_worth.liabilities)}</div>
                  <div className="delta">MoM <span className="bad">+0.6%</span></div>
                </div>
              </div>

              <div className="bar" title="Allocation (cash/stocks/crypto)">
                <span style={{ width: "16%", background: "var(--warn)" }}></span>
                <span style={{ width: "69%", background: "var(--accent)" }}></span>
                <span style={{ width: "15%", background: "var(--good)" }}></span>
              </div>

              <div className="legend">
                <span className="dot"><i style={{ background: "var(--warn)" }}></i>Cash 16%</span>
                <span className="dot"><i style={{ background: "var(--accent)" }}></i>Stocks 69%</span>
                <span className="dot"><i style={{ background: "var(--good)" }}></i>Crypto 15%</span>
              </div>

              <div className="mini" style={{ marginTop: 12 }}>
                <h3>Net Worth Trend</h3>
                <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <div className="muted" style={{ textAlign: "center", lineHeight: 1.4 }}>
                    Placeholder chart area<br />
                    Net worth over time (monthly snapshots)
                  </div>
                </div>
              </div>

              <div className="hintTag">Live</div>
              <div className="actions">
                <button className="btn" disabled>View holdings</button>
                <button className="btn" disabled>View trends</button>
                <button className="btn" disabled>Update snapshot</button>
              </div>
            </div>

            <div className="card">
              <h2>Cash Flow — {month}</h2>
              <div className="split">
                <div className="mini">
                  <h3>Income</h3>
                  <div className="big small">{formatMoney(spendingSummary?.income_total)}</div>
                  <div className="muted">
                    {spendingSummary?.income_categories.length ? (
                      spendingSummary.income_categories.slice(0, 4).map((c) => (
                        <div key={c.category}>{c.category} — {formatMoney(c.amount)}</div>
                      ))
                    ) : (
                      <span>No categorized income yet.</span>
                    )}
                  </div>
                </div>
                <div className="mini">
                  <h3>Expenses</h3>
                  <div className="big small">{formatMoney(spendingSummary?.expense_total)}</div>
                  <div className="muted">Breakdown in the next card.</div>
                </div>
              </div>

              <div className="mini" style={{ marginTop: 12 }}>
                <h3>Net Cash Flow</h3>
                <div className="big small">{formatMoney(spendingSummary?.net)}</div>
                <div className="muted">
                  Savings rate:{" "}
                  <span className="good">
                    {spendingSummary?.savings_rate == null ? "—" : `${Math.round(spendingSummary.savings_rate * 100)}%`}
                  </span>
                </div>
              </div>
              <div className="hintTag">Live</div>
              <div className="actions">
                <button className="btn" disabled>View monthly breakdown</button>
                <button className="btn" disabled>View transaction ledger</button>
                <button className="btn" disabled>Category mapping</button>
              </div>
            </div>

            <div className="card">
              <h2>Expenses — Credit Cards</h2>
              <div className="split">
                <div className="mini">
                  <h3>This month spend</h3>
                  <div className="big small">{formatMoney(creditCardSummary?.total_spend)}</div>
                </div>
                <div className="mini">
                  <h3>Utilization</h3>
                  <div className="big small">
                    {creditCardSummary?.cards.length
                      ? `${Math.round(
                          (creditCardSummary.cards.reduce((acc, c) => acc + (c.utilization ?? 0), 0) /
                            creditCardSummary.cards.length) * 100
                        )}%`
                      : "—"}
                  </div>
                  <div className="muted">
                    limit:{" "}
                    {formatMoney(
                      creditCardSummary?.cards.reduce((acc, c) => acc + c.credit_limit, 0)
                    )}
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 10 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Cards</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Card</th>
                      <th className="right">Current bill</th>
                      <th className="right">Due</th>
                    </tr>
                  </thead>
                  <tbody>
                    {creditCardSummary?.cards.map((card) => (
                      <tr key={card.account_id}>
                        <td>{card.card_name}</td>
                        <td className="right">{formatMoney(card.current_due)}</td>
                        <td className="right">{card.due_date}</td>
                      </tr>
                    ))}
                    {creditCardSummary && creditCardSummary.cards.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={3}>No credit cards configured.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="hintTag">Live</div>
              <div className="actions">
                <button className="btn" disabled>Spending details</button>
                <button className="btn" disabled>Category mapping</button>
              </div>
            </div>
          </section>

          <div style={{ height: 14 }}></div>

          <section className="grid g-mid">
            <div className="card">
              <h2>Expense Breakdown</h2>
              <div className="mini">
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>By category</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th className="right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {spendingSummary?.expense_categories.length ? (
                      spendingSummary.expense_categories.map((c) => (
                        <tr key={c.category}>
                          <td>{c.category}</td>
                          <td className="right">{formatMoney(c.amount)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td className="muted" colSpan={2}>No categorized expenses yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="hintTag">Live</div>
            </div>
            <div className="card">
              <h2>Risk</h2>
              <div className="kpi">
                <div className="label">Largest position</div>
                <div className="val">ETH — 14.2%</div>
                <div className="delta">Concentration threshold: <span className="warn">15%</span></div>
              </div>
              <div style={{ height: 10 }}></div>
              <div className="kpi">
                <div className="label">Top 5 positions</div>
                <div className="val">48.6%</div>
                <div className="delta">Target band: 35–55%</div>
              </div>
              <div className="muted" style={{ marginTop: 12 }}>
                Mocked: risk analysis until holdings exposure aggregation is wired.
              </div>
              <div className="actions">
                <button className="btn" disabled>Set thresholds</button>
                <button className="btn" disabled>Risk breakdown</button>
              </div>
            </div>

            <div className="card">
              <h2>Allocation by Geography</h2>
              <div className="mini">
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Country / Region</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Region</th>
                      <th className="right">Value</th>
                      <th className="right">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary?.geography.map((g) => (
                      <tr key={g.country}>
                        <td>{g.country}</td>
                        <td className="right">{formatMoney(g.value)}</td>
                        <td className="right">{g.percent.toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="hintTag">Live</div>
            </div>
          </section>

          <div style={{ height: 14 }}></div>

          <section className="grid g-bot">
            <div className="card">
              <h2>Allocation by Platform</h2>
              <div className="mini">
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Broker / Bank / Exchange</div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Platform</th>
                      <th className="right">Value</th>
                      <th className="right">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {platformAllocation?.items.map((item) => (
                      <tr key={item.platform}>
                        <td><span className="tag">{item.platform}</span></td>
                        <td className="right">{formatMoney(item.value)}</td>
                        <td className="right">{item.percent.toFixed(1)}%</td>
                      </tr>
                    ))}
                    {platformAllocation && platformAllocation.items.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={3}>No platform allocation data yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="hintTag">Live</div>
            </div>

            <div className="card">
              <h2>Trends (Monthly)</h2>
              <div className="mini" style={{ height: 250, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div className="muted" style={{ textAlign: "center", lineHeight: 1.4 }}>
                  Placeholder chart area<br />
                  Net worth + portfolio value over time (monthly snapshots)
                </div>
              </div>
              <div className="hintTag muted">Mocked</div>
              <div className="actions">
                <button className="btn" disabled>Net worth trend</button>
                <button className="btn" disabled>Spending trend</button>
                <button className="btn" disabled>Export snapshot CSV</button>
              </div>
            </div>

            <div className="card">
              <h2>Top Holdings (Overall)</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Class</th>
                    <th>Geo</th>
                    <th>Platform</th>
                    <th className="right">% NW</th>
                    <th className="right">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.top_holdings.map((h) => (
                    <tr key={`overall-${h.asset_id}`}>
                      <td>{h.symbol}</td>
                      <td className="muted">{h.asset_class}</td>
                      <td className="muted">—</td>
                      <td className="muted">—</td>
                      <td className="right">{h.percent_of_networth.toFixed(1)}%</td>
                      <td className="right">{formatMoney(h.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="hintTag muted">Mocked</div>
            </div>
          </section>

          <footer className="footer">
            Next drill-down screens suggested: Holdings, Spending, Ingestion, Trends, Risk.
            <span className="footerAction">
              <Link className="btn" to="/accounts/new">Add account</Link>
            </span>
          </footer>
        </>
      )}
    </div>
  );
}
