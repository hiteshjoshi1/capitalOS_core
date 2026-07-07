import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CashDeposits, CryptoSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import ValueTrendChart from "../components/ValueTrendChart";

type LoadState = "idle" | "loading" | "ready" | "error";

const STABLECOINS = new Set(["USDC", "USDT"]);

export default function CashOverview() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [cryptoSummary, setCryptoSummary] = useState<CryptoSummary | null>(null);
  const [cashDeposits, setCashDeposits] = useState<CashDeposits | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [crypto, deposits] = await Promise.all([
          api.cryptoSummary(month, baseCurrency),
          api.cashDeposits(month, baseCurrency),
        ]);
        setCryptoSummary(crypto);
        setCashDeposits(deposits);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [month, baseCurrency]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatCompactMoney = (value?: number | null) =>
    value == null
      ? "—"
      : `${currencyPrefix} ${value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`;

  const stablecoins = useMemo(() => {
    const tokens = (cryptoSummary?.top_holdings ?? []).filter((t) => STABLECOINS.has((t.symbol || "").toUpperCase()));
    return tokens;
  }, [cryptoSummary]);

  const stablecoinTotal = stablecoins.reduce((acc, t) => acc + (t.value_base ?? 0), 0);

  return (
    <PageShell
      title="Cash Overview"
      subtitle="Bank cash, broker cash, and stablecoin balances."
      activeRoute="/cash"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
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
      {state === "loading" && <div className="card">Loading…</div>}
      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <>
          <section className="grid" style={{ marginBottom: 16 }}>
            <div className="card">
              <div className="stockHoldingsHeader">
                <h2>Cash Snapshot</h2>
                <div className="muted stockHoldingsMeta">
                  Current as of {cashDeposits?.current_cash_as_of?.slice(0, 10) ?? "—"}
                </div>
              </div>
              <div className="split">
                <div className="mini">
                  <h3>Current total</h3>
                  <div className="big small">{formatMoney(cashDeposits?.current_total)}</div>
                </div>
                <div className="mini">
                  <h3>Snapshot total</h3>
                  <div className="big small">{formatMoney(cashDeposits?.snapshot_total)}</div>
                </div>
                <div className="mini">
                  <h3>Delta</h3>
                  <div className={`big small ${(cashDeposits?.delta_abs ?? 0) >= 0 ? "good" : "bad"}`}>
                    {cashDeposits?.delta_abs == null
                      ? "—"
                      : `${cashDeposits.delta_abs >= 0 ? "+" : "-"}${formatMoney(Math.abs(cashDeposits.delta_abs))}`}
                  </div>
                </div>
              </div>
            </div>

            <div className="card">
              <h2>Cash Deposits</h2>
              <div className="mini">
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Grouped by bank, broker, or wallet source</div>
                <div className="tableWrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th className="right">Value</th>
                      <th className="right">% of Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cashDeposits?.items.map((item) => (
                      <tr key={item.source}>
                        <td>{item.source}</td>
                        <td className="right">{formatMoney(item.value)}</td>
                        <td className="right">{item.percent.toLocaleString(undefined, { maximumFractionDigits: 2 })}%</td>
                      </tr>
                    ))}
                    {cashDeposits && cashDeposits.items.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={3}>No cash deposits yet.</td>
                      </tr>
                    )}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th>Total</th>
                      <th className="right">{formatMoney(cashDeposits?.total)}</th>
                      <th className="right">{cashDeposits?.total ? "100%" : "0%"}</th>
                    </tr>
                  </tfoot>
                </table>
                </div>
              </div>
            </div>
          </section>

          <section className="grid g-mid">
            <div className="card">
              <h2>Currency Breakdown</h2>
              <div className="mini">
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Current vs selected snapshot</div>
                <div className="tableWrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Currency</th>
                      <th className="right">Current</th>
                      <th className="right">Snapshot</th>
                      <th className="right">Delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cashDeposits?.currency_breakdown?.map((c) => (
                      <tr key={c.currency}>
                        <td>{c.currency}</td>
                        <td className="right">{formatMoney(c.current_value)}</td>
                        <td className="right">{formatMoney(c.snapshot_value)}</td>
                        <td className={`right ${c.delta_abs >= 0 ? "good" : "bad"}`}>
                          {c.delta_abs >= 0 ? "+" : "-"}
                          {formatMoney(Math.abs(c.delta_abs))}
                        </td>
                      </tr>
                    ))}
                    {cashDeposits?.currency_breakdown && cashDeposits.currency_breakdown.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={4}>No cash balances yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                </div>
              </div>
            </div>

            <div className="card">
              <h2>Stablecoins</h2>
              <div className="mini">
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>USDC / USDT holdings</div>
                <div className="big small">{formatMoney(stablecoinTotal)}</div>
                <div className="tableWrap">
                <table className="table" style={{ marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>Token</th>
                      <th className="right">Qty</th>
                      <th className="right">Value</th>
                      <th>Chain</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stablecoins.map((t) => (
                      <tr key={`${t.symbol}-${t.chain}-${t.wallet_id ?? ""}`}>
                        <td>{t.symbol}</td>
                        <td className="right">{t.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })}</td>
                        <td className="right">{formatMoney(t.value_base)}</td>
                        <td className="muted">{t.chain.toUpperCase()}</td>
                      </tr>
                    ))}
                    {stablecoins.length === 0 && (
                      <tr>
                        <td className="muted" colSpan={4}>No stablecoin balances found.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                </div>
              </div>
            </div>

            <div className="card valueTrendCard valueTrendCardWide">
              <div className="stockHoldingsHeader">
                <h2>Six-Month Cash Trend</h2>
                <div className="muted stockHoldingsMeta">Snapshot-based month history</div>
              </div>
              <div className="valueTrendValue">
                <span>Current cash value</span>
                <strong>{formatMoney(cashDeposits?.current_total)}</strong>
              </div>
              <ValueTrendChart
                points={cashDeposits?.trend ?? []}
                ariaLabel="Six-month cash trend"
                formatMoney={formatMoney}
                formatCompactMoney={formatCompactMoney}
              />
            </div>
          </section>
        </>
      )}
    </PageShell>
  );
}
