import { useEffect, useMemo, useState } from "react";
import { api } from "./lib/api";
import type { Account, Platform, DashboardSummary } from "./lib/api";
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
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [month, setMonth] = useState<string>(currentMonthYYYYMM());

  const mom = summary?.net_worth_change?.vs_prev_month;
  const yoy = summary?.net_worth_change?.vs_prev_year;


  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        //hardcode
        const [h, p, a, s] = await Promise.all([
          api.health(),
          api.platforms(),
          api.accounts(),
          api.dashboardSummary(month, "prev_month,prev_year")
        ]);
        setHealth(h.status);
        setPlatforms(p);
        setAccounts(a);
        setState("ready");
        setSummary(s);
      } catch (e: any) {
        setErr(e?.message ?? String(e));
        setState("error");
      }
    })();
  }, [month]);

  const platformsById = useMemo(() => {
    const m = new Map<number, Platform>();
    for (const p of platforms) m.set(p.id, p);
    return m;
  }, [platforms]);

  return (
    <div className="wrap">
      <header className="header">
        <div>
          <div className="title">CapitalOS</div>
          <div className="subtitle">Local-first personal finance control plane. Numbers below are placeholders for UI visualization.</div>
        </div>

        <div className="pillRow">
          <span className="pill">API: {health}</span>
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
          <section className="grid top">
            <div className="card">
              <div className="cardTitle">Net Worth</div>
              <div className="big">
                <div className="big">S$ {summary?.net_worth.total?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}</div>
                <div className="muted" style={{ marginTop: 6 }}>

                  MoM:{" "}
                  {mom
                    ? `S$ ${mom.abs.toLocaleString()} (${mom.pct == null ? "—" : `${(mom.pct * 100).toFixed(1)}%`})`
                    : "—"}
                  {" · "}
                  YoY:{" "}
                  {yoy
                    ? `S$ ${yoy.abs.toLocaleString()} (${yoy.pct == null ? "—" : `${(yoy.pct * 100).toFixed(1)}%`})`
                    : "—"}
                </div>
                <div className="muted">
                  Cash: S$ {summary?.net_worth.cash?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"} ·
                  Stocks/Funds: S$ {summary?.net_worth.stocks_funds?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"} ·
                  Crypto: S$ {summary?.net_worth.crypto?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
              </div>
              <div className="muted">
                Wired next: <code>/dashboard/summary</code>
              </div>
              <div className="actions">
                <button className="btn" disabled>View holdings</button>
                <button className="btn" disabled>View trends</button>
              </div>
            </div>

            <div className="card">
              <div className="cardTitle">Cash Flow (Monthly)</div>
              <div className="big">
                <div className="big">S$ {summary?.cash_flow.net?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}</div>
                <div className="muted">
                  Income: S$ {summary?.cash_flow.income?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"} ·
                  Expenses: S$ {summary?.cash_flow.expenses?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"} ·
                  Savings rate: {summary?.cash_flow.savings_rate == null ? "—" : `${Math.round(summary.cash_flow.savings_rate * 100)}%`}
                </div>

              </div>
              <div className="muted">
                Wired next: <code>/spending/summary</code>
              </div>
              <div className="actions">
                <button className="btn" disabled>Monthly breakdown</button>
                <button className="btn" disabled>Ledger</button>
              </div>
            </div>

            <div className="card">
              <div className="cardTitle">Top Holdings</div>

              <table className="table">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Class</th>
                    <th>Value</th>
                    <th>% NW</th>
                  </tr>
                </thead>

                <tbody>
                  {summary?.top_holdings.map(h => (
                    <tr key={h.asset_id}>
                      <td>{h.symbol}</td>
                      <td className="muted">{h.asset_class}</td>
                      <td>S$ {h.value.toLocaleString()}</td>
                      <td>{h.percent_of_networth.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <div className="cardTitle">Quick Risk</div>
              <div className="big">—</div>
              <div className="muted">
                Wired next: <code>/dashboard/top-holdings</code>
              </div>
              <div className="actions">
                <button className="btn" disabled>Thresholds</button>
              </div>
            </div>
          </section>

          {/* Middle row: Platform allocation (real data) */}
          <section className="grid mid">
            <div className="card">
              <div className="cardTitle">Platforms (Reference)</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Country</th>
                  </tr>
                </thead>
                <tbody>
                  {platforms.map((p) => (
                    <tr key={p.id}>
                      <td><code>{p.code}</code></td>
                      <td>{p.name}</td>
                      <td className="muted">{p.platform_type}</td>
                      <td className="muted">{p.country}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="card">
              <div className="cardTitle">Accounts (Configured)</div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Account Type</th>
                    <th>Platform</th>
                    <th>Currency</th>
                    <th>Country</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a) => {
                    const p = a.platform_id ? platformsById.get(a.platform_id) : undefined;
                    return (
                      <tr key={a.id}>
                        <td>{a.name}</td>
                        <td className="muted">{a.account_type}</td>
                        <td>
                          {p ? (
                            <>
                              <code>{p.code}</code> <span className="muted">({p.platform_type})</span>
                            </>
                          ) : (
                            <span className="muted">{a.platform}</span>
                          )}
                        </td>
                        <td className="muted">{a.currency}</td>
                        <td className="muted">{a.country ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="actions" style={{ marginTop: 10 }}>
                <Link className="btn" to="/accounts/new">Add account</Link>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
