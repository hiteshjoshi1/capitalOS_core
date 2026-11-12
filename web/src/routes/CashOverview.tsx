import { useCallback, useId, useMemo } from "react";
import { api } from "../lib/api";
import { snapshotMonthOf, useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import "../App.css";
import "./CashOverview.css";
import MonthBar from "../components/MonthBar";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import StackedBar from "../components/StackedBar";
import TrendBarChart from "../components/TrendBarChart";
import RefreshingRegion from "../components/RefreshingRegion";
import { formatDate, formatMoney, formatMoneyCompact, formatMonth, formatNumber, formatPercent, formatSignedMoney } from "../lib/format";
import { chartColor, donutGradient } from "../lib/chartColors";
import { noDataFor } from "../lib/delta";
import { useBaseCurrency } from "../context/CurrencyContext";
import LoadError from "../components/LoadError";
import { describeShares } from "../lib/chartA11y";
import StatusPill from "../components/StatusPill";

/** Shown until /crypto/stablecoins answers with the symbols it counts. */
const STABLECOIN_LABEL_FALLBACK = ["USDC", "USDT"];
export default function CashOverview() {
  const [month, setMonth] = useSelectedMonth();
  const donutDescId = useId();
  const [baseCurrency] = useBaseCurrency();
  // #148: one resource per call, so the stablecoin card never holds up the cash numbers,
  // and the previous month stays on screen while the next one loads. #149: the card reads
  // the lean /crypto/stablecoins, not the whole crypto summary.
  const deposits = useApiResource(resourceKey("cashDeposits", month, baseCurrency), () =>
    api.cashDeposits(month, baseCurrency),
  );
  const crypto = useApiResource(resourceKey("cryptoStablecoins", month, baseCurrency), () =>
    api.cryptoStablecoins(month, baseCurrency),
  );
  const cashDeposits = deposits.data ?? null;
  const cryptoStablecoins = crypto.data ?? null;

  // Label amounts with the currency they were computed in: while a currency switch loads,
  // the previous currency's numbers stay on screen and must keep their own prefix.
  const shownCurrency = cashDeposits?.base_currency || baseCurrency;
  const money = useCallback((value?: number | null) => formatMoney(value, shownCurrency), [shownCurrency]);
  const compactMoney = useCallback((value?: number | null) => formatMoneyCompact(value, shownCurrency), [shownCurrency]);

  const stablecoins = cryptoStablecoins?.holdings ?? [];
  const stablecoinTotal = cryptoStablecoins?.total_base ?? 0;
  const stablecoinLabel = (cryptoStablecoins?.symbols ?? STABLECOIN_LABEL_FALLBACK).join(" / ");

  const accountItems = useMemo(
    () => (cashDeposits?.items ?? []).map((item) => ({ label: item.source, value: item.value, percent: item.percent })),
    [cashDeposits],
  );

  const currencySegments = useMemo(() => {
    const breakdown = cashDeposits?.currency_breakdown ?? [];
    const sum = breakdown.reduce((acc, c) => acc + Math.max(0, c.current_value), 0) || 1;
    return breakdown.map((c, idx) => ({
      key: c.currency,
      label: c.currency,
      percent: (Math.max(0, c.current_value) / sum) * 100,
      color: chartColor(idx),
      valueLabel: `${money(c.current_value)} (${formatSignedMoney(c.delta_abs, shownCurrency)})`,
    }));
  }, [cashDeposits, money, shownCurrency]);

  const trendPoints = useMemo(
    () =>
      (cashDeposits?.trend ?? [])
        .filter((point) => point.value != null)
        .map((point) => ({
          month: point.month,
          value: point.value as number,
          displayValue: compactMoney(point.value),
          tone: "neutral" as const,
          // #241 (D-61): the open month is live, month to date.
          isLive: point.is_live === true,
        })),
    [cashDeposits, compactMoney],
  );

  // #232: the headline counts stablecoins as cash; net worth (Overview, History) counts them
  // under Crypto (D-42). Say so, with the amount, so the two "cash" figures can be reconciled.
  const stablecoinsInTotal = cashDeposits?.current_stablecoin_total ?? 0;
  const stablecoinNote =
    stablecoinsInTotal > 0
      ? ` · Includes ${money(stablecoinsInTotal)} in stablecoins, which net worth counts under Crypto`
      : "";

  // #397 (U13): the per-account table, the first check when net worth looks off.
  const accountRows = cashDeposits?.accounts ?? [];
  const compareLabel = cashDeposits?.compare_month ? formatMonth(cashDeposits.compare_month, "medium") : "last month";
  // #397 (U14): foreign-currency cash revalued at today's rates (the bridge's cash FX part).
  const fxRevaluation = cashDeposits?.fx_revaluation ?? null;

  // #224: a compare month with no cash data says so; it isn't a zero baseline.
  const missingReason = cashDeposits?.snapshot_missing ? noDataFor(cashDeposits.compare_month) : null;

  return (
    <PageShell
      title="Cash Overview"
      subtitle="Bank cash, broker cash, and stablecoin balances as of any month."
      activeRoute="/cash"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      monthBar={<MonthBar month={month} onMonthChange={setMonth} />}
    >
      {deposits.isLoading && <div className="card" role="status">Loading…</div>}
      {deposits.error && (
        <LoadError title="Couldn't load cash" error={deposits.error.message} onRetry={() => void deposits.reload().catch(() => undefined)} />
      )}

      {cashDeposits && (
        <RefreshingRegion className="wealthOverviewLayout" busy={deposits.isFetching || crypto.isFetching}>
          <HeroMetricCard
            eyebrow={cashDeposits?.is_live ? "CURRENT CASH" : `CASH — ${snapshotMonthOf(cashDeposits?.net_worth_boundary_at, cashDeposits?.as_of_month ?? month)}`}
            value={money(cashDeposits?.current_total)}
            delta={{
              abs: cashDeposits?.delta_abs,
              compareValue: cashDeposits?.snapshot_total,
              currency: shownCurrency,
              missingReason,
            }}
            insightText={`As of ${formatDate(cashDeposits?.current_cash_as_of)} · vs ${cashDeposits?.compare_month ? formatMonth(cashDeposits.compare_month, "medium") : "last month"} (${formatDate(cashDeposits?.snapshot_cash_as_of)})${stablecoinNote}`}
          />

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Allocation</p>
              <h2 className="cashFlowSectionTitle">Where the cash sits</h2>
            </div>
            {accountItems.length === 0 ? (
              <div className="card muted">No cash deposits yet.</div>
            ) : (
              <div className="card cashFlowDonutLayout" style={{ padding: 28 }}>
                <div
                  className="cashFlowDonutChart"
                  style={{ background: donutGradient(accountItems.map((item) => item.percent)) }}
                  role="img"
                  aria-label="Cash by account"
                  aria-describedby={donutDescId}
                >
                  <span id={donutDescId} className="srOnly">{describeShares("Cash by account", accountItems)}</span>
                  <div className="cashFlowDonutCenter">
                    <span className="label">Total</span>
                    <strong>{money(cashDeposits?.total)}</strong>
                  </div>
                </div>
                <div className="cashFlowLegendList">
                  {accountItems.map((item, idx) => (
                    <div className="cashFlowLegendRow" key={item.label}>
                      <span className="cashFlowLegendLabel">
                        <i style={{ background: chartColor(idx) }} />
                        <span className="cashFlowLegendText">{item.label}</span>
                      </span>
                      <span className="muted">
                        {money(item.value)} <strong>{formatPercent(item.percent, { scale: "points" })}</strong>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Signals</p>
              <h2 className="cashFlowSectionTitle">Currency mix and stablecoins</h2>
            </div>
            <div className="grid g-mid">
              <div className="card" style={{ padding: 24 }}>
                <p className="cashFlowCardTitle">Currency exposure</p>
                <StackedBar layout="rows" segments={currencySegments} ariaLabel="Currency mix" />
              </div>

              <div className="card" style={{ padding: 24 }}>
                <div className="cashFlowCardHeader" style={{ marginBottom: 6 }}>
                  <p className="cashFlowCardTitle" style={{ margin: 0 }}>Stablecoins</p>
                  <span className="muted">{stablecoinLabel}</span>
                </div>
                <div className="big small">{cryptoStablecoins ? money(stablecoinTotal) : "—"}</div>
                <div className="listRows" style={{ marginTop: 8 }}>
                  {crypto.error ? (
                    <p className="muted">Stablecoin balances couldn't load: {crypto.error.message}</p>
                  ) : !cryptoStablecoins ? (
                    <p className="muted" role="status">Loading stablecoins…</p>
                  ) : stablecoins.length === 0 ? (
                    <p className="muted">No stablecoin balances found.</p>
                  ) : (
                    stablecoins.map((t) => (
                      <div className="listRow" key={`${t.symbol}-${t.chain}-${t.wallet_id ?? ""}`}>
                        <div className="listRowMain">
                          <span className="listRowTitle">{t.symbol}</span>
                          <span className="listRowMeta">
                            <span>{formatNumber(t.amount, 6)}</span>
                            <span>{t.chain.toUpperCase()}</span>
                          </span>
                        </div>
                        <div className="listRowValue">{money(t.value_base)}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </section>

          <section aria-labelledby="cash-accounts-heading">
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Accounts</p>
              <h2 className="cashFlowSectionTitle" id="cash-accounts-heading">
                Cash by account
              </h2>
            </div>
            <div className="card" style={{ padding: 24 }}>
              {accountRows.length === 0 ? (
                <p className="muted">No cash accounts yet.</p>
              ) : (
                <>
                  <p className="muted cashAccountsNote">
                    Balance now, the change vs {compareLabel}, and how recent each account's data is. Check here first
                    when net worth looks off.
                  </p>
                  <div className="listRows" data-testid="cash-accounts">
                    {accountRows.map((row) => (
                      <div className="listRow" key={`${row.kind}-${row.account_id ?? row.label}`}>
                        <div className="listRowMain">
                          <span className="listRowTitle">
                            {row.label}{" "}
                            {row.stale ? <StatusPill tone="warn" label="Overdue" /> : null}
                          </span>
                          <span className="listRowMeta">
                            <span>{row.platform}</span>
                            {row.currencies && row.currencies.length > 0 ? <span>{row.currencies.join(", ")}</span> : null}
                            <span>{row.last_data_date ? `Data ${formatDate(row.last_data_date)}` : "No data now"}</span>
                          </span>
                        </div>
                        <div className="listRowValue cashAccountValue">
                          <span>{money(row.current_value)}</span>
                          <span className={`cashAccountDelta ${row.delta_abs > 0 ? "isUp" : row.delta_abs < 0 ? "isDown" : ""}`}>
                            {formatSignedMoney(row.delta_abs, shownCurrency)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </section>

          {fxRevaluation ? (
            <section aria-labelledby="cash-fx-heading">
              <div className="cashFlowSectionHeading">
                <p className="wealthEyebrow">Exchange rates</p>
                <h2 className="cashFlowSectionTitle" id="cash-fx-heading">
                  Foreign cash revalued
                </h2>
              </div>
              <div className="card" style={{ padding: 24 }} data-testid="cash-fx-revaluation">
                {fxRevaluation.items.length === 0 ? (
                  <p className="muted">No foreign-currency cash at {compareLabel}, so exchange rates moved nothing.</p>
                ) : (
                  <>
                    <div className="big small">{formatSignedMoney(fxRevaluation.total, shownCurrency)}</div>
                    <p className="muted cashAccountsNote">
                      What exchange rates alone did to the foreign-currency cash you held at {compareLabel} (
                      {formatDate(fxRevaluation.from_at)} to {formatDate(fxRevaluation.to_at)}), stablecoins not included.
                      The same figure as the FX line for foreign-currency cash in Overview's "This month".
                    </p>
                    <div className="listRows">
                      {fxRevaluation.items.map((item) => (
                        <div className="listRow" key={item.currency}>
                          <div className="listRowMain">
                            <span className="listRowTitle">{item.currency} cash</span>
                            <span className="listRowMeta">
                              <span>{money(item.start_value)} at {compareLabel}</span>
                            </span>
                          </div>
                          <div className="listRowValue">{formatSignedMoney(item.fx_effect, shownCurrency)} from FX</div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </section>
          ) : null}

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Six-month cash trend</h2>
              <div className="muted stockHoldingsMeta">
                Month-end snapshots{trendPoints.some((point) => point.isLive) ? " · MTD: this month to date, live" : ""}
              </div>
            </div>
            <TrendBarChart points={trendPoints} ariaLabel="Six-month cash trend" />
          </div>
        </RefreshingRegion>
      )}
    </PageShell>
  );
}
