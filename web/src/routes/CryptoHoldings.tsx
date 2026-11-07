import { useCallback, useMemo, useState } from "react";
import { api } from "../lib/api";
import { snapshotMonthOf, useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import { formatDate, formatMoney, formatMoneyCompact, formatMonth, formatNumber, formatPercent } from "../lib/format";
import { noDataFor, noRateFor } from "../lib/delta";
import { chartColor } from "../lib/chartColors";
import "../App.css";
import MonthBar from "../components/MonthBar";
import PageShell from "../components/PageShell";
import FxNote from "../components/FxNote";
import HeroMetricCard from "../components/HeroMetricCard";
import Delta from "../components/Delta";
import TrendBarChart from "../components/TrendBarChart";
import StackedBar from "../components/StackedBar";
import { useBaseCurrency } from "../context/CurrencyContext";
import LoadError from "../components/LoadError";


export default function CryptoHoldings() {
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency] = useBaseCurrency();
  const [showDust, setShowDust] = useState<boolean>(false);
  const resource = useApiResource(resourceKey("cryptoSummary", month, baseCurrency), () =>
    api.cryptoSummary(month, baseCurrency),
  );
  const summary = resource.data ?? null;

  // The currency the shown numbers are in (the previous one while a switch loads).
  const shownCurrency = summary?.base_currency || baseCurrency;
  const money = useCallback((value?: number | null) => formatMoney(value, shownCurrency), [shownCurrency]);
  const compactMoney = useCallback((value?: number | null) => formatMoneyCompact(value, shownCurrency), [shownCurrency]);
  /** A holding's base-currency value last month: the % comes from it, in the same currency
   * as the amount, so the two never disagree (#131: "-S$ 13,764 (+3.1%)"). */
  const previousBase = (valueBase?: number | null, changeBase?: number | null) =>
    valueBase != null && changeBase != null ? valueBase - changeBase : null;

  const allHoldings = useMemo(() => summary?.top_holdings ?? [], [summary?.top_holdings]);
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
          displayValue: compactMoney(point.value),
          tone: "neutral" as const,
          // #241 (D-61): the open month is live, month to date.
          isLive: point.is_live === true,
        })),
    [summary, compactMoney],
  );

  // #224: no baseline is a sentence, not a delta the size of the whole holding.
  const missingReason = summary?.snapshot_missing
    ? summary.snapshot_missing_reason === "no_fx_rate"
      ? noRateFor(summary.compare_month)
      : noDataFor(summary.compare_month)
    : null;

  return (
    <PageShell
      title="Crypto Holdings"
      subtitle="Wallet, token, and chain-level exposure as of any month."
      activeRoute="/crypto/holdings"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      monthBar={<MonthBar month={month} onMonthChange={setMonth} />}
    >
      {resource.isLoading && <div className="card" role="status">Loading…</div>}
      {resource.error && (
        <LoadError title="Couldn't load crypto holdings" error={resource.error.message} onRetry={() => void resource.reload().catch(() => undefined)} />
      )}

      {summary && (
        <RefreshingRegion className="wealthOverviewLayout" busy={resource.isFetching}>
          <HeroMetricCard
            eyebrow={summary?.is_live ? "CURRENT CRYPTO VALUE" : `CRYPTO VALUE — ${snapshotMonthOf(summary?.as_of, summary?.month ?? month)}`}
            value={money(summary?.total_crypto_base)}
            delta={{
              abs: summary?.snapshot_delta_base,
              compareValue: summary?.snapshot_total_base,
              currency: shownCurrency,
              missingReason,
            }}
            insightText={
              (summary?.is_live
                ? `${formatMoney(summary?.total_crypto_usd, "USD")} · Holdings as of ${formatDate(summary?.holdings_as_of ?? summary?.last_refreshed_at)} (${holdingsFresh ? "fresh" : "stale"}) · Prices as of ${formatDate(summary?.price_as_of ?? summary?.last_refreshed_at)} (${pricesFresh ? "fresh" : "stale"}${summary?.refresh_triggered ? ", refreshing" : ""})`
                : `${formatMoney(summary?.total_crypto_usd, "USD")} · historical snapshot as of ${formatDate(summary?.as_of)}`) +
              // #232: the previous figure names its month and the date of its snapshot.
              ` · vs ${summary?.compare_month ? formatMonth(summary.compare_month, "medium") : "last month"}` +
              (summary?.snapshot_as_of && !summary?.snapshot_missing ? ` (${formatDate(summary.snapshot_as_of)})` : "")
            }
          />
          <FxNote sources={[summary]} />

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Exposure</p>
              <h2 className="cashFlowSectionTitle">Breakdown by chain and wallet</h2>
            </div>
            <div className="grid g-mid">
              <div className="card" role="group" aria-label="Crypto chain exposure chart">
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
                      color: chartColor(idx),
                      valueLabel: `${money(item.total_base)} · ${formatPercent(item.percent, { scale: "points" })}`,
                    }))}
                  />
                )}
              </div>

              <div className="card" role="group" aria-label="Crypto wallet exposure chart">
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
                      color: chartColor(idx),
                      valueLabel: `${money(item.total_base)} · ${formatPercent(item.percent ?? 0, { scale: "points" })}`,
                    }))}
                  />
                )}
              </div>
            </div>
          </section>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Six-month value trend</h2>
              <div className="muted stockHoldingsMeta">
                Month-end snapshots ending {summary?.month ?? month}
                {trendPoints.some((point) => point.isLive) ? " · MTD: this month to date, live" : ""}
              </div>
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
                Show holdings under USD 10
              </label>
            </div>
            <div className="muted stockHoldingsMeta" style={{ marginBottom: 8 }}>
              {showDust
                ? `Showing all ${allHoldings.length} holdings, including dust under USD 10`
                : `Showing ${visibleHoldings.length} of ${allHoldings.length} holdings${hiddenDustCount > 0 ? ` · ${hiddenDustCount} hidden under USD 10` : ""}`}
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
                        <span>{formatNumber(h.amount, 6)} qty</span>
                        <span>{h.price_provider ?? h.holdings_provider ?? "—"}</span>
                        {h.wallet_label ? <span>{h.wallet_label}</span> : null}
                      </span>
                    </div>
                    <div className="listRowValue">
                      {money(h.value_base)}
                      <span className="listRowValueSecondary">
                        <Delta
                          abs={h.value_change_base}
                          compareValue={previousBase(h.value_base, h.value_change_base)}
                          currency={shownCurrency}
                        />
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </RefreshingRegion>
      )}
    </PageShell>
  );
}
