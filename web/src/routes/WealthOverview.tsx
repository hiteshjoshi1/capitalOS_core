import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { AssetClassFreshness, NetWorthFreshness } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import { currentMonthYYYYMM } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import { chartColor, donutGradient } from "../lib/chartColors";
import "../App.css";
import PageShell from "../components/PageShell";
import FxNote from "../components/FxNote";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import LoadError from "../components/LoadError";
import { describeShares } from "../lib/chartA11y";
import Delta from "../components/Delta";
import { missingBaselineReason } from "../lib/delta";

const PORTFOLIO_REFRESH_TOPIC = "portfolio-refresh";
const PORTFOLIO_REFRESH_DEBOUNCE_MS = 750;

// Daily-refreshed sources (IBKR, Coinbase, market quotes) go "carried" once they
// miss the cadence a live source implies; matches the backend's QUOTE_STALE_DAYS default.
const DAILY_SOURCE_FRESH_DAYS = 3;
// Bank/broker cash is manual-cadence (monthly-or-less uploads) — a much longer window
// still counts as "fresh" for that kind of source.
const MANUAL_SOURCE_FRESH_DAYS = 31;

/** Formats amounts in `currency`: each panel passes the currency its own data is in, so a
 * panel still showing the previous currency (while a switch loads, #148) keeps its label. */
function moneyFormatter(currency: string) {
  return (value?: number | null) => fmt.formatMoney(value, currency);
}

function ageInDays(iso?: string | null): number | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, Math.floor((Date.now() - ts) / 86_400_000));
}

function formatChipAsOf(iso?: string | null): string {
  const days = ageInDays(iso);
  if (days == null) return "no data";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  const label = fmt.formatDate(iso).replace(/ \d{4}$/, "");
  return `${label} · ${days}d`;
}

type FreshnessBucket = "fresh" | "carried" | "missing";

function freshnessBucket(iso: string | null | undefined, freshDays: number): FreshnessBucket {
  const days = ageInDays(iso);
  if (days == null) return "missing";
  return days <= freshDays ? "fresh" : "carried";
}

function AssetFreshnessChip({
  label,
  freshness,
  freshDays,
}: {
  label: string;
  freshness?: AssetClassFreshness | null;
  freshDays: number;
}) {
  const mostRecentAt = freshness?.most_recent_at ?? null;
  const stalestAt = freshness?.stalest_at ?? null;
  // Worst case drives the warning dot — a fresh headline shouldn't hide a stale account.
  const bucket = freshnessBucket(stalestAt ?? mostRecentAt, freshDays);
  const hasSpread = Boolean(stalestAt && mostRecentAt && stalestAt !== mostRecentAt);
  return (
    <span className={`coFreshnessChip${bucket === "carried" ? " coFreshnessChipCarried" : ""}`} tabIndex={0}>
      <span
        className={`coFreshnessDot coFreshnessDot${bucket === "fresh" ? "Fresh" : bucket === "carried" ? "Carried" : "Missing"}`}
        aria-hidden="true"
      />
      <strong>{label}</strong>
      <span>{formatChipAsOf(mostRecentAt)}</span>
      <span className="coFreshnessTooltip" role="tooltip">
        <span className="coFreshnessTooltipRow">
          <span>Most recent</span>
          <strong>
            {freshness?.most_recent_label ?? "—"} · {formatChipAsOf(mostRecentAt)}
          </strong>
        </span>
        {hasSpread ? (
          <span className="coFreshnessTooltipRow">
            <span>Stalest</span>
            <strong>
              {freshness?.stalest_label ?? "—"} · {formatChipAsOf(stalestAt)}
            </strong>
          </span>
        ) : null}
      </span>
    </span>
  );
}

export default function WealthOverview() {
  // Pinned once per page load — this page always shows the current month; there is
  // no month selector here (see Wealth Timeline Phase 1 plan for why).
  const month = useMemo(() => currentMonthYYYYMM(), []);

  const [baseCurrency] = useBaseCurrency();
  const allocDescId = useId();
  const [allocView, setAllocView] = useState<"platform" | "asset_class">("platform");
  const [holdingsView, setHoldingsView] = useState<"holdings" | "movers" | "today">("holdings");

  // #148: each panel is its own resource. Bootstrap is the lean call, so the hero renders
  // as soon as it resolves without waiting on the heavier summary/spending/platform
  // calls; on a currency switch every panel keeps its previous numbers until its own
  // reply lands (and a slow earlier reply can never overwrite a later currency).
  const bootstrapRes = useApiResource(resourceKey("dashboardBootstrap", month, baseCurrency), () =>
    api.dashboardBootstrap(month, baseCurrency),
  );
  const summaryRes = useApiResource(
    resourceKey("dashboardSummary", month, "prev_month,prev_year", baseCurrency),
    () => api.dashboardSummary(month, "prev_month,prev_year", baseCurrency),
  );
  const spendingRes = useApiResource(resourceKey("spendingSummary", month, baseCurrency), () =>
    api.spendingSummary(month, baseCurrency),
  );
  // The platform-allocation response carries no base_currency, so remember it alongside.
  const platformRes = useApiResource(resourceKey("platformAllocation", month, baseCurrency), async () => ({
    currency: baseCurrency,
    allocation: await api.platformAllocation(month, baseCurrency),
  }));
  const sinceUpdateRes = useApiResource(resourceKey("netWorthSinceUpdate", baseCurrency), () =>
    api.netWorthSinceUpdate(baseCurrency),
  );

  const bootstrap = bootstrapRes.data ?? null;
  const summary = summaryRes.data ?? null;
  const spendingSummary = spendingRes.data ?? null;
  const platformAllocation = platformRes.data?.allocation ?? null;
  const sinceUpdate = sinceUpdateRes.data ?? null;
  const selectedBaseCurrency = baseCurrency || bootstrap?.base_currency || "SGD";

  const reloadAllRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    reloadAllRef.current = () => {
      for (const res of [bootstrapRes, summaryRes, spendingRes, platformRes, sinceUpdateRes]) {
        void res.reload().catch(() => undefined);
      }
    };
  });

  const refreshTimerRef = useRef<number | null>(null);
  useEffect(() => {
    const unsubscribe = subscribeToRealtimeTopic(PORTFOLIO_REFRESH_TOPIC, {
      onEvent: () => {
        if (refreshTimerRef.current != null) window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = window.setTimeout(() => {
          // A background refresh: the numbers stay on screen until the new ones land.
          reloadAllRef.current();
        }, PORTFOLIO_REFRESH_DEBOUNCE_MS);
      },
    });

    return () => {
      if (refreshTimerRef.current != null) window.clearTimeout(refreshTimerRef.current);
      unsubscribe();
    };
  }, []);

  // #151: a panel whose call failed says so (with a retry) instead of showing "—",
  // which read the same as zero (#130 finding 7.5).
  const retry = (res: { reload: () => Promise<unknown> }) => () => void res.reload().catch(() => undefined);

  const formatMoney = moneyFormatter(bootstrap?.base_currency || selectedBaseCurrency);
  const summaryCurrency = summary?.base_currency || selectedBaseCurrency;
  const sinceUpdateCurrency = sinceUpdate?.base_currency || selectedBaseCurrency;
  const formatSummaryMoney = moneyFormatter(summaryCurrency);
  const formatSpendingMoney = moneyFormatter(spendingSummary?.base_currency || selectedBaseCurrency);
  const platformCurrency = platformRes.data?.currency || selectedBaseCurrency;
  const formatPlatformMoney = moneyFormatter(platformCurrency);

  // Hero headline, freshness, liabilities, and the asset-class allocation view all
  // come from bootstrap — none of them need to wait on the heavier summary call.
  const currentNetWorth = bootstrap?.current_net_worth ?? bootstrap?.net_worth ?? null;
  const currentNetWorthAsOf = bootstrap?.current_net_worth_as_of ?? bootstrap?.net_worth_as_of ?? null;
  const currentFreshness: NetWorthFreshness | null = bootstrap?.current_net_worth_freshness ?? null;
  const currentNetWorthTotal = currentNetWorth?.total ?? 0;

  const stocksPct = currentNetWorthTotal
    ? ((currentNetWorth?.stocks_funds ?? 0) / currentNetWorthTotal) * 100
    : 0;
  const cryptoPct = currentNetWorthTotal
    ? ((currentNetWorth?.crypto ?? 0) / currentNetWorthTotal) * 100
    : 0;
  const cashPct = currentNetWorthTotal
    ? ((currentNetWorth?.cash ?? 0) / currentNetWorthTotal) * 100
    : 0;

  const assetClassItems = useMemo(
    () =>
      [
        {
          label: "Stocks & Funds",
          value: currentNetWorth?.stocks_funds ?? 0,
          percent: stocksPct,
        },
        { label: "Crypto", value: currentNetWorth?.crypto ?? 0, percent: cryptoPct },
        { label: "Cash", value: currentNetWorth?.cash ?? 0, percent: cashPct },
      ].filter((i) => i.percent > 0),
    [currentNetWorth, stocksPct, cryptoPct, cashPct],
  );

  const platformItems = useMemo(
    () =>
      (platformAllocation?.items ?? []).map((item) => ({
        label: formatPlatformLabel(item.platform),
        value: item.value,
        percent: item.percent,
      })),
    [platformAllocation],
  );

  const activeAllocItems = allocView === "platform" ? platformItems : assetClassItems;
  const formatAllocMoney = allocView === "platform" ? formatPlatformMoney : formatMoney;
  const allocCurrency = allocView === "platform" ? platformCurrency : bootstrap?.base_currency || selectedBaseCurrency;
  const allocTotal =
    allocView === "platform"
      ? (platformAllocation?.total ?? 0)
      : (currentNetWorth?.total ?? 0);

  // The hero headline is the live net worth, so its deltas are the live comparisons
  // (live vs the latest completed month-end, and that month-end a year earlier), #133.
  const heroChange = summary?.current_net_worth_change ?? summary?.net_worth_change;
  const prevMonthChange = heroChange?.vs_prev_month;
  const prevYearChange = heroChange?.vs_prev_year;
  const topHoldings = (summary?.top_holdings ?? []).slice(0, 4);
  const topMovers = summary?.top_movers ?? null;
  const liabilities = bootstrap?.net_worth?.liabilities ?? null;

  return (
    <PageShell
      title="Wealth Overview"
      subtitle="Portfolio composition and the most important balance-sheet signals."
      headerActions={
        <BaseCurrencyPicker />
      }
    >
      {bootstrapRes.isLoading ? (
        <div className="card" role="status">Loading…</div>
      ) : null}
      {bootstrapRes.error ? (
        <LoadError title="Couldn't load net worth" error={bootstrapRes.error.message} onRetry={() => void bootstrapRes.reload().catch(() => undefined)} />
      ) : null}

      {bootstrap ? (
        <RefreshingRegion
          className="wealthOverviewLayout"
          busy={[bootstrapRes, summaryRes, spendingRes, platformRes, sinceUpdateRes].some((r) => r.isFetching && r.data !== undefined)}
        >

          {/* ── Hero card ─────────────────────────────────────────────── */}
          <article className="coHeroCard">
            <div className="coHeroCardHeader">
              <p className="coHeroEyebrow">CURRENT NET WORTH</p>
            </div>
            <div className="coHeroValueRow">
              <span className="coHeroValue">{formatMoney(currentNetWorth?.total)}</span>
              {prevMonthChange ? (
                <Delta
                  variant="chip"
                  show="pct"
                  abs={prevMonthChange.abs}
                  pct={prevMonthChange.pct}
                  currency={summaryCurrency}
                  missingReason={missingBaselineReason(prevMonthChange)}
                />
              ) : null}
            </div>

            <div className="coFreshnessRow" aria-label="Data freshness by asset class">
              <AssetFreshnessChip label="Stocks" freshness={currentFreshness?.stocks} freshDays={DAILY_SOURCE_FRESH_DAYS} />
              <AssetFreshnessChip label="Crypto" freshness={currentFreshness?.crypto} freshDays={DAILY_SOURCE_FRESH_DAYS} />
              <AssetFreshnessChip label="Cash" freshness={currentFreshness?.cash} freshDays={MANUAL_SOURCE_FRESH_DAYS} />
            </div>

            {currentNetWorthAsOf ? (
              <p className="coHeroFreshness">As of {fmt.formatDate(currentNetWorthAsOf)}</p>
            ) : null}
            <FxNote sources={[bootstrap, summary]} />

            <div className="coHeroDeltaRow">
              {sinceUpdate?.net_worth_change ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">
                    SINCE LAST UPDATE{sinceUpdate.compare_as_of ? ` (${formatChipAsOf(sinceUpdate.compare_as_of)})` : ""}
                  </span>
                  <strong>
                    <Delta
                      abs={sinceUpdate.net_worth_change.abs}
                      pct={sinceUpdate.net_worth_change.pct}
                      currency={sinceUpdateCurrency}
                      missingReason={sinceUpdate.net_worth_change.baseline_missing ? "no earlier update to compare with" : null}
                    />
                  </strong>
                </div>
              ) : sinceUpdateRes.isLoading ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">SINCE LAST UPDATE</span>
                  <strong className="muted">…</strong>
                </div>
              ) : sinceUpdateRes.error ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">SINCE LAST UPDATE</span>
                  <LoadError compact title="Couldn't load" onRetry={retry(sinceUpdateRes)} />
                </div>
              ) : null}
              {prevMonthChange ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">VS LAST MONTH</span>
                  <strong>
                    <Delta
                      abs={prevMonthChange.abs}
                      pct={prevMonthChange.pct}
                      currency={summaryCurrency}
                      missingReason={missingBaselineReason(prevMonthChange)}
                    />
                  </strong>
                </div>
              ) : summaryRes.isLoading ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">VS LAST MONTH</span>
                  <strong className="muted">…</strong>
                </div>
              ) : summaryRes.error ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">VS LAST MONTH</span>
                  <LoadError compact title="Couldn't load" onRetry={retry(summaryRes)} />
                </div>
              ) : null}
              {prevYearChange ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel">VS LAST YEAR</span>
                  <strong>
                    <Delta
                      abs={prevYearChange.abs}
                      pct={prevYearChange.pct}
                      currency={summaryCurrency}
                      missingReason={missingBaselineReason(prevYearChange)}
                    />
                  </strong>
                </div>
              ) : null}
              <Link className="coHeroHistoryTeaser" to="/wealth/history">
                View history →
              </Link>
            </div>
          </article>

          {/* ── Allocation section ─────────────────────────────────────── */}
          <section aria-labelledby="wealth-alloc-heading">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow" id="wealth-alloc-heading">
                  ALLOCATION
                </p>
                <h2 className="coSectionTitle">Where the money sits</h2>
              </div>
              <div className="coSegmentedControl" role="group" aria-label="Allocation view">
                <button
                  type="button"
                  className={`coSegmentedBtn${allocView === "platform" ? " coSegmentedBtnActive" : ""}`}
                  onClick={() => setAllocView("platform")}
                >
                  By platform
                </button>
                <button
                  type="button"
                  className={`coSegmentedBtn${allocView === "asset_class" ? " coSegmentedBtnActive" : ""}`}
                  onClick={() => setAllocView("asset_class")}
                >
                  By asset class
                </button>
              </div>
            </div>

            {allocView === "platform" && platformRes.isLoading ? (
              <p className="muted" role="status">Loading allocation…</p>
            ) : allocView === "platform" && platformRes.error && !platformAllocation ? (
              <LoadError compact title="Couldn't load the allocation" error={platformRes.error} onRetry={retry(platformRes)} />
            ) : activeAllocItems.length > 0 ? (
              <div className="coAllocationCard">
                <div
                  className="coAllocationDonut"
                  style={{ background: donutGradient(activeAllocItems.map((item) => item.percent)) }}
                  role="img"
                  aria-label="Allocation donut chart"
                  aria-describedby={allocDescId}
                >
                  <span id={allocDescId} className="srOnly">
                    {describeShares(
                      allocView === "platform" ? "Allocation by platform" : "Allocation by asset class",
                      activeAllocItems,
                    )}
                  </span>
                  <div className="coAllocationInner">
                    <span className="coAllocationTotalLabel">TOTAL</span>
                    <strong className="coAllocationTotalValue">
                      {fmt.formatMoneyCompact(allocTotal, allocCurrency)}
                    </strong>
                  </div>
                </div>

                <div className="coAllocationLegend">
                  {activeAllocItems.map((item, idx) => (
                    <div key={item.label} className="coAllocationRow">
                      <div className="coAllocationRowLeft">
                        <span
                          className="coAllocationDot"
                          style={{ background: chartColor(idx) }}
                          aria-hidden="true"
                        />
                        <span className="coAllocationName">{item.label}</span>
                      </div>
                      <div className="coAllocationRowRight">
                        <span className="coAllocationValue">{formatAllocMoney(item.value)}</span>
                        <strong className="coAllocationPct">{fmt.formatPercent(item.percent, { scale: "points" })}</strong>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="muted">No allocation data for this period.</p>
            )}
          </section>

          {/* ── Signals section ────────────────────────────────────────── */}
          <section aria-labelledby="wealth-signals-heading">
            <div className="coSectionHeaderSimple">
              <p className="coEyebrow" id="wealth-signals-heading">
                SIGNALS
              </p>
              <h2 className="coSectionTitle">Cash flow, risk, and movement</h2>
            </div>

            <div className="coSignalsGrid">
              <article className="coSignalCard">
                <p className="coSignalEyebrow">CASH FLOW</p>
                {spendingRes.isLoading ? (
                  <p className="muted" role="status">Loading…</p>
                ) : spendingRes.error && !spendingSummary ? (
                  <LoadError compact title="Couldn't load cash flow" error={spendingRes.error} onRetry={retry(spendingRes)} />
                ) : (
                  <>
                    <p className="coSignalValue">{formatSpendingMoney(spendingSummary?.net)}</p>
                    <p className="coSignalMeta">
                      {spendingSummary
                        ? `Income ${formatSpendingMoney(spendingSummary.income_total)} · Expenses ${formatSpendingMoney(spendingSummary.expense_total)} · Saved ${fmt.formatPercent(spendingSummary.savings_rate)}`
                        : "—"}
                    </p>
                    <FxNote sources={[spendingSummary]} />
                  </>
                )}
                <Link className="wealthInlineLink" to="/cash-flow">
                  Open cash flow
                </Link>
              </article>

              <article className="coSignalCard">
                <p className="coSignalEyebrow">LIABILITIES</p>
                <p className="coSignalValue">{formatMoney(liabilities)}</p>
                <p className="coSignalMeta">Outstanding obligations vs current net worth.</p>
                <Link className="wealthInlineLink" to="/liabilities">
                  Open liabilities
                </Link>
              </article>
            </div>

            <article className="coHoldingsCard">
              <div className="coHoldingsHeader">
                <h3 className="coHoldingsTitle">Largest positions</h3>
                <div className="coSegmentedControl" role="group" aria-label="Holdings view">
                  <button
                    type="button"
                    className={`coSegmentedBtn${holdingsView === "holdings" ? " coSegmentedBtnActive" : ""}`}
                    onClick={() => setHoldingsView("holdings")}
                  >
                    Holdings
                  </button>
                  <button
                    type="button"
                    className={`coSegmentedBtn${holdingsView === "movers" ? " coSegmentedBtnActive" : ""}`}
                    onClick={() => setHoldingsView("movers")}
                  >
                    Movers
                  </button>
                  <button
                    type="button"
                    className={`coSegmentedBtn${holdingsView === "today" ? " coSegmentedBtnActive" : ""}`}
                    onClick={() => setHoldingsView("today")}
                  >
                    Today
                  </button>
                </div>
              </div>

              <div className="coHoldingsList">
                {summaryRes.isLoading ? (
                  <p className="muted" role="status">Loading holdings…</p>
                ) : holdingsView !== "today" && summaryRes.error && !summary ? (
                  <LoadError compact title="Couldn't load positions" error={summaryRes.error} onRetry={retry(summaryRes)} />
                ) : holdingsView === "holdings" ? (
                  topHoldings.length > 0 ? (
                    topHoldings.map((h) => (
                      <div key={h.asset_id ?? h.symbol} className="coHoldingRow">
                        <div className="coHoldingLeft">
                          <strong className="coHoldingSymbol">{h.symbol}</strong>
                          <span className="coHoldingClass">{h.asset_class.toUpperCase()}</span>
                        </div>
                        <div className="coHoldingRight">
                          <strong className="coHoldingValue">{formatSummaryMoney(h.value)}</strong>
                          <span className="coHoldingPct">
                            {fmt.formatPercent(h.percent_of_networth, { scale: "points" })}
                          </span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="muted">No holdings returned for this period.</p>
                  )
                ) : holdingsView === "movers" ? (
                  topMovers ? (
                    [
                      ...(topMovers.gainers ?? []).slice(0, 2),
                      ...(topMovers.detractors ?? []).slice(0, 2),
                    ].map((row) => (
                      <div
                        key={`${row.asset_class}-${row.symbol}`}
                        className="coHoldingRow"
                      >
                        <div className="coHoldingLeft">
                          <strong className="coHoldingSymbol">{row.symbol}</strong>
                          <span className="coHoldingClass">{row.asset_class.toUpperCase()}</span>
                        </div>
                        <div className="coHoldingRight">
                          <strong className="coHoldingValue">
                            <Delta abs={row.delta_abs} currency={summaryCurrency} show="abs" />
                          </strong>
                          <span className="coHoldingPct">
                            {row.delta_pct == null
                              ? `vs ${row.compare_month}`
                              : fmt.formatPercent(row.delta_pct, { signed: true })}
                          </span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="muted">No mover data for this period.</p>
                  )
                ) : sinceUpdateRes.isLoading ? (
                  <p className="muted" role="status">Loading today's movers…</p>
                ) : sinceUpdateRes.error && !sinceUpdate ? (
                  <LoadError compact title="Couldn't load today's movers" error={sinceUpdateRes.error} onRetry={retry(sinceUpdateRes)} />
                ) : sinceUpdate?.top_movers ? (
                  [
                    ...(sinceUpdate.top_movers.gainers ?? []).slice(0, 3),
                    ...(sinceUpdate.top_movers.detractors ?? []).slice(0, 2),
                  ].length > 0 ? (
                    [
                      ...(sinceUpdate.top_movers.gainers ?? []).slice(0, 3),
                      ...(sinceUpdate.top_movers.detractors ?? []).slice(0, 2),
                    ].map((row) => (
                      <div
                        key={`today-${row.asset_class}-${row.symbol}`}
                        className="coHoldingRow"
                      >
                        <div className="coHoldingLeft">
                          <strong className="coHoldingSymbol">{row.symbol}</strong>
                          <span className="coHoldingClass">{row.asset_class.toUpperCase()}</span>
                        </div>
                        <div className="coHoldingRight">
                          <strong className="coHoldingValue">
                            <Delta abs={row.delta_abs} currency={sinceUpdateCurrency} show="abs" />
                          </strong>
                          <span className="coHoldingPct">
                            {row.delta_pct == null
                              ? "—"
                              : fmt.formatPercent(row.delta_pct, { signed: true })}
                          </span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="muted">No movement since the last update.</p>
                  )
                ) : (
                  <p className="muted">No mover data yet.</p>
                )}
              </div>
            </article>
          </section>
        </RefreshingRegion>
      ) : null}
    </PageShell>
  );
}
