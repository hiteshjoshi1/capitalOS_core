import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { CryptoSummary } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import TrendBarChart from "../components/TrendBarChart";
import StackedBar from "../components/StackedBar";

const EXPOSURE_COLORS = ["#4f8cff", "#1fb981", "#f59f43", "#7d67ff", "#ef6ca8", "#2ebac6", "#f4cf5d", "#8f9db2"];

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

  const allHoldings = summary?.top_holdings ?? [];
  const visibleHoldings = useMemo(
    () => allHoldings.filter((h) => showDust || h.value_usd >= 10),
    [allHoldings, showDust],
  );
  const hiddenDustCount = allHoldings.length - allHoldings.filter((h) => h.value_usd >= 10).length;

  const holdingsFresh = !(summary?.stale_holdings ?? summary?.is_stale);
  const pricesFresh = !(summary?.stale_prices ?? summary?.is_stale);

  const trendPoints = useMemo(
    () =>
      (summary?.trend ?? [])
        .filter((point) => point.value != null)
        .map((point) => ({
          month: point.month,
          value: point.value as number,
          displayValue: formatCompactMoney(point.value),
          tone: "neutral" as const,
        })),
    [summary, currencyPrefix],
  );

  const deltaPositive = (summary?.snapshot_delta_base ?? 0) >= 0;

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
        <div className="wealthOverviewLayout">
          <HeroMetricCard
            eyebrow="CURRENT CRYPTO VALUE"
            value={formatMoney(summary?.total_crypto_base)}
            deltaChip={{
              text: `${deltaPositive ? "+" : "-"}${summary?.snapshot_delta_pct == null ? "—" : Math.abs(summary.snapshot_delta_pct * 100).toFixed(1) + "%"}`,
              positive: deltaPositive,
            }}
            insightText={`USD ${summary?.total_crypto_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? "—"} · Holdings as of ${formatDate(summary?.holdings_as_of ?? summary?.last_refreshed_at)} (${holdingsFresh ? "fresh" : "stale"}) · Prices as of ${formatDate(summary?.price_as_of ?? summary?.last_refreshed_at)} (${pricesFresh ? "fresh" : "stale"}${summary?.refresh_triggered ? ", refreshing" : ""})`}
          />

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Exposure</p>
              <h2 className="cashFlowSectionTitle">Breakdown by chain and wallet</h2>
            </div>
            <div className="grid g-mid">
              <div className="card" aria-label="Crypto chain exposure chart">
                <p className="cashFlowCardTitle">Chain mix</p>
                {(summary?.chain_exposure ?? []).length === 0 ? (
                  <p className="muted">No exposure data yet.</p>
                ) : (
                  <StackedBar
                    layout="rows"
                    ariaLabel="Crypto chain exposure chart"
                    segments={(summary?.chain_exposure ?? []).map((item, idx) => ({
                      key: item.chain,
                      label: item.chain,
                      percent: item.percent,
                      color: EXPOSURE_COLORS[idx % EXPOSURE_COLORS.length],
                      valueLabel: `${formatMoney(item.total_base)} · ${item.percent.toFixed(1)}%`,
                    }))}
                  />
                )}
              </div>

              <div className="card" aria-label="Crypto wallet exposure chart">
                <p className="cashFlowCardTitle">Wallet mix</p>
                {(summary?.wallet_exposure ?? []).length === 0 ? (
                  <p className="muted">No exposure data yet.</p>
                ) : (
                  <StackedBar
                    layout="rows"
                    ariaLabel="Crypto wallet exposure chart"
                    segments={(summary?.wallet_exposure ?? []).map((item, idx) => ({
                      key: item.wallet_id,
                      label: item.label ?? `${item.address.slice(0, 6)}…${item.address.slice(-4)}`,
                      percent: item.percent ?? 0,
                      color: EXPOSURE_COLORS[idx % EXPOSURE_COLORS.length],
                      valueLabel: `${formatMoney(item.total_base)} · ${(item.percent ?? 0).toFixed(1)}%`,
                    }))}
                  />
                )}
              </div>
            </div>
          </section>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Six-month value trend</h2>
              <div className="muted stockHoldingsMeta">Snapshot history ending {summary?.month ?? month}</div>
            </div>
            <TrendBarChart points={trendPoints} ariaLabel="Six-month crypto trend" />
          </div>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Top holdings</h2>
              <label className="pill" style={{ display: "inline-flex" }}>
                <input
                  type="checkbox"
                  checked={showDust}
                  onChange={(e) => setShowDust(e.target.checked)}
                  style={{ marginRight: 6 }}
                />
                Show holdings under $10
              </label>
            </div>
            <div className="muted stockHoldingsMeta" style={{ marginBottom: 8 }}>
              {showDust
                ? `Showing all ${allHoldings.length} holdings, including dust under $10`
                : `Showing ${visibleHoldings.length} of ${allHoldings.length} holdings${hiddenDustCount > 0 ? ` · ${hiddenDustCount} hidden under $10` : ""}`}
            </div>
            <div className="listRows">
              {visibleHoldings.length === 0 ? (
                <div className="muted">No crypto holdings yet.</div>
              ) : (
                visibleHoldings.slice(0, 25).map((h) => (
                  <div className="listRow" key={`${h.symbol}-${h.chain}-${h.wallet_id ?? ""}`}>
                    <div className="listRowMain">
                      <span className="listRowTitle">
                        {h.symbol}
                        <span className="tag">{h.chain.toUpperCase()}</span>
                      </span>
                      <span className="listRowMeta">
                        <span>{h.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })} qty</span>
                        <span>{h.price_provider ?? h.holdings_provider ?? "—"}</span>
                        {h.wallet_label ? <span>{h.wallet_label}</span> : null}
                      </span>
                    </div>
                    <div className={`listRowValue ${(h.value_change_pct ?? 0) >= 0 ? "good" : "bad"}`}>
                      {formatMoney(h.value_base)}
                      <span className="listRowValueSecondary">{formatDelta(h.value_change_base, h.value_change_pct)}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
