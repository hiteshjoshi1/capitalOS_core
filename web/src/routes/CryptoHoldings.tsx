import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { CryptoSummary } from "../lib/api";
import "../App.css";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function CryptoHoldings() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<CryptoSummary | null>(null);
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [showDust, setShowDust] = useState<boolean>(false);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const data = await api.cryptoSummary(baseCurrency);
        setSummary(data);
        setState("ready");
      } catch (e: any) {
        setErr(e?.message ?? String(e));
        setState("error");
      }
    })();
  }, [baseCurrency]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;

  return (
    <div className="wrap">
      <header className="header">
        <div className="titleBlock">
          <div className="title">Crypto Holdings</div>
          <div className="subtitle">Detailed wallet, token, and chain-level exposure.</div>
        </div>
        <div className="pillRow">
          <Link className="pill" to="/">Dashboard</Link>
          <Link className="pill" to="/crypto">Wallets</Link>
          <Link className="pill" to="/holdings">Stock Holdings</Link>
          <Link className="pill" to="/cash">Cash</Link>
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
            >
              <option value="SGD">SGD</option>
              <option value="USD">USD</option>
              <option value="HKD">HKD</option>
              <option value="INR">INR</option>
            </select>
          </label>
        </div>
      </header>

      {state === "loading" && <div className="card">Loading…</div>}
      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <section className="grid g-mid">
          <div className="card">
            <h2>Overview</h2>
            <div className="split">
              <div className="mini">
                <h3>Total (base)</h3>
                <div className="big small">{formatMoney(summary?.total_crypto_base)}</div>
                <div className="muted">
                  USD {summary?.total_crypto_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
              </div>
              <div className="mini">
                <h3>Last refresh</h3>
                <div className="muted">
                  {summary?.last_refreshed_at ?? "—"}
                </div>
                <div className="muted">
                  {summary?.is_stale ? "Stale" : "Fresh"}{" "}
                  {summary?.refresh_triggered ? "(refreshing)" : ""}
                </div>
              </div>
            </div>
            <div className="split" style={{ marginTop: 12 }}>
              <div className="mini">
                <h3>ETH exposure</h3>
                <div className="big small">{formatMoney(summary?.eth_exposure_base)}</div>
                <div className="muted">
                  USD {summary?.eth_exposure_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
              </div>
              <div className="mini">
                <h3>Other tokens</h3>
                <div className="big small">{formatMoney(summary?.token_exposure_base)}</div>
                <div className="muted">
                  USD {summary?.token_exposure_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
                <div className="muted">
                  Tokens priced: {summary?.priced_token_count ?? 0} / {summary?.token_count ?? 0}
                </div>
              </div>
            </div>
            <div className="split" style={{ marginTop: 12 }}>
              <div className="mini">
                <h3>ETH</h3>
                <div className="big small">{summary?.eth.balance?.toFixed(4) ?? "0"}</div>
                <div className="muted">
                  USD {summary?.eth.value_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
              </div>
              <div className="mini">
                <h3>SOL</h3>
                <div className="big small">{summary?.sol.balance?.toFixed(4) ?? "0"}</div>
                <div className="muted">
                  USD {summary?.sol.value_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <h2>Top Holdings</h2>
            <label className="pill" style={{ marginBottom: 8, display: "inline-flex" }}>
              <input
                type="checkbox"
                checked={showDust}
                onChange={(e) => setShowDust(e.target.checked)}
                style={{ marginRight: 6 }}
              />
              Show &lt;$10 tokens
            </label>
            <table className="table">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th className="right">Qty</th>
                  <th className="right">Unit</th>
                  <th className="right">Value</th>
                  <th>Chain</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const filtered = (summary?.top_holdings ?? []).filter((h) => {
                    if (h.value_usd < 10 && !showDust) return false;
                    return true;
                  });
                  if (!filtered.length) {
                    return (
                      <tr>
                        <td className="muted" colSpan={5}>No crypto holdings yet.</td>
                      </tr>
                    );
                  }
                  return filtered.slice(0, 25).map((h) => {
                    const unit = h.amount > 0 ? h.value_base / h.amount : null;
                    return (
                      <tr key={`${h.symbol}-${h.chain}-${h.wallet_id ?? ""}`}>
                        <td>{h.symbol}</td>
                        <td className="right">{h.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })}</td>
                        <td className="right">{unit == null ? "—" : formatMoney(unit, 2)}</td>
                        <td className="right">{formatMoney(h.value_base)}</td>
                        <td className="muted">{h.chain.toUpperCase()}</td>
                      </tr>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>

          {summary?.wallet_exposure && summary.wallet_exposure.length > 0 && (
            <div className="card">
              <h2>Exposure by Wallet</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Wallet</th>
                    <th>Chain</th>
                    <th className="right">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.wallet_exposure.map((w) => (
                    <tr key={w.wallet_id}>
                      <td>{w.label ?? `${w.address.slice(0, 6)}…${w.address.slice(-4)}`}</td>
                      <td className="muted">{w.chain_type}:{w.chain}</td>
                      <td className="right">{formatMoney(w.total_base)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {summary?.wallet_chain_exposure && summary.wallet_chain_exposure.length > 0 && (
            <div className="card">
              <h2>Exposure by Wallet + Chain</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Wallet</th>
                    <th>Chain</th>
                    <th className="right">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.wallet_chain_exposure.map((w) => (
                    <tr key={`${w.wallet_id}-${w.chain}`}>
                      <td>{w.wallet_id.slice(0, 6)}…{w.wallet_id.slice(-4)}</td>
                      <td className="muted">{w.chain}</td>
                      <td className="right">{formatMoney(w.total_base)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
