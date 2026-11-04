import { useCallback, useMemo } from "react";
import { api } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import StackedBar from "../components/StackedBar";
import TrendBarChart from "../components/TrendBarChart";
import RefreshingRegion from "../components/RefreshingRegion";
import { formatDate, formatMoney, formatMoneyCompact, formatMonth, formatNumber, formatPercent, formatSignedMoney } from "../lib/format";
import { chartColor, donutGradient } from "../lib/chartColors";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";

const STABLECOINS = new Set(["USDC", "USDT"]);
export default function CashOverview() {
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency] = useBaseCurrency();
  // #148: one resource per call, so the stablecoin card (crypto summary) never holds up
  // the cash numbers, and the previous month stays on screen while the next one loads.
  const deposits = useApiResource(resourceKey("cashDeposits", month, baseCurrency), () =>
    api.cashDeposits(month, baseCurrency),
  );
  const crypto = useApiResource(resourceKey("cryptoSummary", month, baseCurrency), () =>
    api.cryptoSummary(month, baseCurrency),
  );
  const cashDeposits = deposits.data ?? null;
  const cryptoSummary = crypto.data ?? null;

  // Label amounts with the currency they were computed in: while a currency switch loads,
  // the previous currency's numbers stay on screen and must keep their own prefix.
  const shownCurrency = cashDeposits?.base_currency || baseCurrency;
  const money = useCallback((value?: number | null) => formatMoney(value, shownCurrency), [shownCurrency]);
  const compactMoney = useCallback((value?: number | null) => formatMoneyCompact(value, shownCurrency), [shownCurrency]);

  const stablecoins = useMemo(() => {
    const tokens = (cryptoSummary?.top_holdings ?? []).filter((t) => STABLECOINS.has((t.symbol || "").toUpperCase()));
    return tokens;
  }, [cryptoSummary]);

  const stablecoinTotal = stablecoins.reduce((acc, t) => acc + (t.value_base ?? 0), 0);

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
        })),
    [cashDeposits, compactMoney],
  );

  const deltaPositive = (cashDeposits?.delta_abs ?? 0) >= 0;
  const deltaPct = cashDeposits?.delta_pct;

  return (
    <PageShell
      title="Cash Overview"
      subtitle="Bank cash, broker cash, and stablecoin balances as of any month."
      activeRoute="/cash"
      secondaryNavItem={{ label: "Import Statements", to: "/ingest" }}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <BaseCurrencyPicker />
        </>
      )}
    >
      {deposits.isLoading && <div className="card">Loading…</div>}
      {deposits.error && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{deposits.error.message}</pre>
        </div>
      )}

      {cashDeposits && (
        <RefreshingRegion className="wealthOverviewLayout" busy={deposits.isFetching || crypto.isFetching}>
          <HeroMetricCard
            eyebrow={cashDeposits?.is_live ? "CURRENT CASH" : `CASH — ${cashDeposits?.as_of_month ?? month}`}
            value={money(cashDeposits?.current_total)}
            deltaChip={
              deltaPct == null
                ? null
                : { text: formatPercent(deltaPct, { signed: true }), positive: deltaPositive }
            }
            insightText={`As of ${formatDate(cashDeposits?.current_cash_as_of)} · vs ${cashDeposits?.compare_month ? formatMonth(cashDeposits.compare_month, "medium") : "last month"} (${formatDate(cashDeposits?.snapshot_cash_as_of)})`}
          />

          <section>
            <div className="cashFlowSectionHeading">
              <p className="wealthEyebrow">Allocation</p>
              <h2 className="cashFlowSectionTitle">Where the cash sits</h2>
            </div>
            {accountItems.length === 0 ? (
              <div className="card muted">No cash deposits yet.</div>
            ) : (
              <div className="card cashFlowDonutLayout" style={{ padding: 28 }} aria-label="Cash by account">
                <div className="cashFlowDonutChart" style={{ background: donutGradient(accountItems.map((item) => item.percent)) }}>
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
                  <span className="muted">USDC / USDT</span>
                </div>
                <div className="big small">{cryptoSummary ? money(stablecoinTotal) : "—"}</div>
                <div className="listRows" style={{ marginTop: 8 }}>
                  {crypto.error ? (
                    <p className="muted">Stablecoin balances couldn't load: {crypto.error.message}</p>
                  ) : !cryptoSummary ? (
                    <p className="muted">Loading stablecoins…</p>
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

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>Six-month cash trend</h2>
              <div className="muted stockHoldingsMeta">Snapshot-based month history</div>
            </div>
            <TrendBarChart points={trendPoints} ariaLabel="Six-month cash trend" />
          </div>
        </RefreshingRegion>
      )}
    </PageShell>
  );
}
