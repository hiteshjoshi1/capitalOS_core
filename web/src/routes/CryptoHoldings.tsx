import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { CryptoSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import ExposurePieCard from "../components/ExposurePieCard";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import ValueTrendChart from "../components/ValueTrendChart";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function CryptoHoldings() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [summary, setSummary] = useState<CryptoSummary | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [showDust, setShowDust] = useState<boolean>(false);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const data = await api.cryptoSummary(month, baseCurrency);
        setSummary(data);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [baseCurrency, month]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number | null, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatCompactMoney = (value?: number | null) =>
    value == null
      ? "—"
      : `${currencyPrefix} ${value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`;
  const formatDate = (value?: string | null) => value?.slice(0, 10) ?? "—";
  const formatDelta = (value?: number | null, pct?: number | null) => {
    if (value == null) {
      return "—";
    }
    return `${value >= 0 ? "+" : "-"}${formatMoney(Math.abs(value))}${pct == null ? "" : ` (${pct >= 0 ? "+" : "-"}${Math.abs(pct * 100).toFixed(1)}%)`}`;
  };

  return (
    <PageShell
      title="Crypto Holdings"
      subtitle="Detailed wallet, token, and chain-level exposure."
      activeRoute="/crypto/holdings"
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
        <section className="grid g-mid">
          <div className="card">
            <h2>Overview</h2>
            <div className="split">
              <div className="mini">
                <h3>Current value</h3>
                <div className="big small">{formatMoney(summary?.total_crypto_base)}</div>
                <div className="muted">
                  USD {summary?.total_crypto_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"}
                </div>
              </div>
              <div className="mini">
                <h3>Snapshot value</h3>
                <div className="big small">{formatMoney(summary?.snapshot_total_base)}</div>
                <div className="muted">{summary?.snapshot_as_of ?? "—"}</div>
              </div>
            </div>
            <div className="split" style={{ marginTop: 12 }}>
              <div className="mini">
                <h3>Snapshot delta</h3>
                <div className={`big small ${(summary?.snapshot_delta_base ?? 0) >= 0 ? "good" : "bad"}`}>
                  {formatDelta(summary?.snapshot_delta_base, summary?.snapshot_delta_pct)}
                </div>
                <div className="muted">Selected month {summary?.month ?? month}</div>
              </div>
              <div className="mini">
                <h3>Holdings as of</h3>
                <div className="big small">{formatDate(summary?.holdings_as_of ?? summary?.last_refreshed_at)}</div>
                <div className="muted">
                  {summary?.stale_holdings ?? summary?.is_stale ? "Stale holdings" : "Fresh holdings"}
                </div>
              </div>
            </div>
            <div className="split" style={{ marginTop: 12 }}>
              <div className="mini">
                <h3>Prices as of</h3>
                <div className="big small">{formatDate(summary?.price_as_of ?? summary?.last_refreshed_at)}</div>
                <div className="muted">
                  {summary?.stale_prices ?? summary?.is_stale ? "Stale prices" : "Fresh prices"} {summary?.refresh_triggered ? "(refreshing)" : ""}
                </div>
              </div>
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
            <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th className="right">Qty</th>
                  <th className="right">Unit</th>
                  <th className="right">Value</th>
                  <th>Chain</th>
                  <th>Provider</th>
                  <th className="right">Price move</th>
                  <th className="right">Value move</th>
                  <th className="right">Snapshot delta</th>
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
                        <td className="muted" colSpan={9}>No crypto holdings yet.</td>
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
                        <td className="muted">{h.price_provider ?? h.holdings_provider ?? "—"}</td>
                        <td className={`right ${(h.price_change_usd ?? 0) >= 0 ? "good" : "bad"}`}>
                          {h.price_change_usd == null ? "—" : `${h.price_change_usd >= 0 ? "+" : "-"}USD ${Math.abs(h.price_change_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                        </td>
                        <td className={`right ${(h.value_change_base ?? 0) >= 0 ? "good" : "bad"}`}>{formatDelta(h.value_change_base, h.value_change_pct)}</td>
                        <td className={`right ${(h.snapshot_delta_base ?? 0) >= 0 ? "good" : "bad"}`}>{formatDelta(h.snapshot_delta_base, h.snapshot_delta_pct)}</td>
                      </tr>
                    );
                  });
                })()}
              </tbody>
            </table>
            </div>
          </div>

          <ExposurePieCard
            title="Exposure by Chain"
            subtitle="Current chain mix"
            items={(summary?.chain_exposure ?? []).map((item) => ({
              label: item.chain,
              value: item.total_base,
              percent: item.percent,
            }))}
            totalLabel={formatMoney(summary?.total_crypto_base)}
            formatMoney={formatMoney}
            ariaLabel="Crypto chain exposure pie chart"
          />

          <ExposurePieCard
            title="Exposure by Wallet"
            subtitle="Current wallet mix"
            items={(summary?.wallet_exposure ?? []).map((item) => ({
              label: item.label ?? `${item.address.slice(0, 6)}…${item.address.slice(-4)}`,
              value: item.total_base,
              percent: item.percent ?? 0,
            }))}
            totalLabel={formatMoney(summary?.total_crypto_base)}
            formatMoney={formatMoney}
            ariaLabel="Crypto wallet exposure pie chart"
          />

          <div className="card valueTrendCard valueTrendCardWide">
            <div className="stockHoldingsHeader">
              <h2>Six-Month Crypto Trend</h2>
              <div className="muted stockHoldingsMeta">Snapshot history ending {summary?.month ?? month}</div>
            </div>
            <div className="valueTrendValue">
              <span>Current crypto value</span>
              <strong>{formatMoney(summary?.total_crypto_base)}</strong>
            </div>
            <ValueTrendChart
              points={summary?.trend ?? []}
              ariaLabel="Six-month crypto trend"
              formatMoney={formatMoney}
              formatCompactMoney={formatCompactMoney}
            />
          </div>
        </section>
      )}
    </PageShell>
  );
}
