import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { AssetClassFreshness, NetWorthFreshness } from "../lib/api";
import { formatPlatformLabel } from "../lib/platformLabels";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import { currentMonthYYYYMM, isPastMonth, snapshotMonthOf, useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import { chartColor, donutGradient } from "../lib/chartColors";
import "../App.css";
import PageShell from "../components/PageShell";
import FxNote from "../components/FxNote";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import MonthControl from "../components/MonthControl";
import LoadError from "../components/LoadError";
import { describeShares } from "../lib/chartA11y";
import Delta from "../components/Delta";
import MonthBridgeCard from "../components/MonthBridgeCard";
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
  const label = fmt.formatDayMonth(iso);
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
  // #223: the shared selected month, like every other page. The current month shows the
  // live headline; a past month shows that month-end snapshot, with that month's comparisons.
  const [month, setMonth] = useSelectedMonth();

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
  // "Since last update" and today's movers are live only: not fetched for a past month.
  const sinceUpdateRes = useApiResource(
    isPastMonth(month) ? null : resourceKey("netWorthSinceUpdate", baseCurrency),
    () => api.netWorthSinceUpdate(baseCurrency),
  );

  const bootstrap = bootstrapRes.data ?? null;
  const summary = summaryRes.data ?? null;
  const spendingSummary = spendingRes.data ?? null;
  const platformAllocation = platformRes.data?.allocation ?? null;
  const selectedBaseCurrency = baseCurrency || bootstrap?.base_currency || "SGD";

  // Live or a past month-end, by the month the hero data is for (while a new month loads,
  // the previous month's numbers stay on screen with their own labels).
  const shownMonth = bootstrap?.as_of_month ?? month;
  const isLive = bootstrap?.is_live ?? !isPastMonth(shownMonth);
  const sinceUpdate = isLive ? (sinceUpdateRes.data ?? null) : null;
  // The month-end actually used: the month before the anchor date (last month, before
  // SNAPSHOT_DAY, still reads the month-end before it, as the backend does).
  const snapshotMonth = snapshotMonthOf(bootstrap?.net_worth_boundary_at, shownMonth);

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
  // #249 (D-65): "since last update" is market movement since the compare date,
  // every holding against its last quote on or before it.
  const sinceUpdateBasisText =
    sinceUpdate?.basis === "quoted_at_compare_date" && sinceUpdate.compare_basis?.price_date
      ? `Moves since ${fmt.formatDate(sinceUpdate.compare_basis.price_date)}, each holding at its last quote on or before that date.`
      : null;
  const olderStatementCount = sinceUpdate?.compare_basis?.older_statement_priced ?? 0;
  const todayFallbackShown = [
    ...(sinceUpdate?.top_movers?.gainers ?? []).slice(0, 3),
    ...(sinceUpdate?.top_movers?.detractors ?? []).slice(0, 2),
  ].some((row) => row.compare_price_fallback);
  const formatSummaryMoney = moneyFormatter(summaryCurrency);
  const formatSpendingMoney = moneyFormatter(spendingSummary?.base_currency || selectedBaseCurrency);
  const platformCurrency = platformRes.data?.currency || selectedBaseCurrency;
  const formatPlatformMoney = moneyFormatter(platformCurrency);

  // Hero headline, freshness, liabilities, and the asset-class allocation view all
  // come from bootstrap — none of them need to wait on the heavier summary call.
  // A past month's headline is its month-end snapshot (`net_worth`), not today's value.
  const currentNetWorth = isLive
    ? (bootstrap?.current_net_worth ?? bootstrap?.net_worth ?? null)
    : (bootstrap?.net_worth ?? null);
  const currentNetWorthAsOf = isLive
    ? (bootstrap?.current_net_worth_as_of ?? bootstrap?.net_worth_as_of ?? null)
    : (bootstrap?.net_worth_as_of ?? null);
  const currentFreshness: NetWorthFreshness | null = bootstrap?.current_net_worth_freshness ?? null;
  // #232: both donuts split gross assets (cash + stocks & funds + crypto), the platform
  // allocation's total; the headline is that minus liabilities, shown under the legend.
  const grossAssets = currentNetWorth
    ? currentNetWorth.cash + currentNetWorth.stocks_funds + currentNetWorth.crypto
    : 0;

  const stocksPct = grossAssets ? ((currentNetWorth?.stocks_funds ?? 0) / grossAssets) * 100 : 0;
  const cryptoPct = grossAssets ? ((currentNetWorth?.crypto ?? 0) / grossAssets) * 100 : 0;
  const cashPct = grossAssets ? ((currentNetWorth?.cash ?? 0) / grossAssets) * 100 : 0;

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
  const allocTotal = allocView === "platform" ? (platformAllocation?.total ?? 0) : grossAssets;

  // The live headline's deltas are the live comparisons (live vs the latest completed
  // month-end, and that month-end a year earlier), #133. A past month's headline is a
  // month-end, so its deltas are that month-end vs the one before and a year before (D-24),
  // labelled with their baseline. Only a summary for the month on screen is used.
  const summaryForMonth = summary && summary.as_of_month === shownMonth ? summary : null;
  const heroChange = isLive
    ? (summaryForMonth?.current_net_worth_change ?? summaryForMonth?.net_worth_change)
    : summaryForMonth?.net_worth_change;
  const prevMonthChange = heroChange?.vs_prev_month;
  const prevYearChange = heroChange?.vs_prev_year;
  // #232: every comparison names its baseline, live or past (live compares with the latest
  // completed month-end, D-24).
  const prevMonthLabel = prevMonthChange
    ? `VS ${fmt.formatMonth(prevMonthChange.compare_month, "medium").toUpperCase()} MONTH-END`
    : "VS LAST MONTH";
  const prevYearLabel = prevYearChange
    ? `VS ${fmt.formatMonth(prevYearChange.compare_month, "medium").toUpperCase()} MONTH-END`
    : "VS LAST YEAR";
  const shownHoldingsView = !isLive && holdingsView === "today" ? "holdings" : holdingsView;
  const topHoldings = (summary?.top_holdings ?? []).slice(0, 4);
  const topMovers = summary?.top_movers ?? null;
  // #232: the liabilities taken off the headline above (live: today's; a past month: its
  // month-end's), not always the last month-end's.
  const liabilities = currentNetWorth?.liabilities ?? null;

  return (
    <PageShell
      title="Wealth Overview"
      subtitle="Portfolio composition and the most important balance-sheet signals."
      headerActions={
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <BaseCurrencyPicker />
        </>
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
              <p className="coHeroEyebrow">
                {isLive ? "CURRENT NET WORTH" : `NET WORTH · ${fmt.formatMonth(snapshotMonth, "medium").toUpperCase()} MONTH-END`}
              </p>
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

            {isLive ? (
              <div className="coFreshnessRow" aria-label="Data freshness by asset class">
                <AssetFreshnessChip label="Stocks" freshness={currentFreshness?.stocks} freshDays={DAILY_SOURCE_FRESH_DAYS} />
                <AssetFreshnessChip label="Crypto" freshness={currentFreshness?.crypto} freshDays={DAILY_SOURCE_FRESH_DAYS} />
                <AssetFreshnessChip label="Cash" freshness={currentFreshness?.cash} freshDays={MANUAL_SOURCE_FRESH_DAYS} />
              </div>
            ) : (
              // #223 (mock-up B in #131): a past month says what it is, with a way back.
              <p className="coHeroPastMonth" role="note">
                Viewing {fmt.formatMonth(snapshotMonth, "medium")} (month-end snapshot) ·{" "}
                <button type="button" className="coHeroBackToLive" onClick={() => setMonth(currentMonthYYYYMM())}>
                  Back to live
                </button>
              </p>
            )}

            {currentNetWorthAsOf ? (
              <p className="coHeroFreshness">As of {fmt.formatDate(currentNetWorthAsOf)}</p>
            ) : null}
            <FxNote sources={[bootstrap, summary]} />

            <div className="coHeroDeltaRow">
              {!isLive ? null : sinceUpdate?.net_worth_change ? (
                <div className="coHeroDelta">
                  <span className="coHeroDeltaLabel" title={sinceUpdateBasisText ?? undefined}>
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
                  {olderStatementCount > 0 ? (
                    <span className="coHeroDeltaNote">
                      {olderStatementCount === 1 ? "1 holding" : `${olderStatementCount} holdings`} vs an older statement price
                    </span>
                  ) : null}
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
                  <span className="coHeroDeltaLabel">{prevMonthLabel}</span>
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
                  <span className="coHeroDeltaLabel">{prevYearLabel}</span>
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

          {/* ── This month's bridge (#240): what moved the headline since the last close ── */}
          <MonthBridgeCard month={month} baseCurrency={selectedBaseCurrency} />

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
                    <span className="coAllocationTotalLabel">GROSS ASSETS</span>
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
                  {currentNetWorth ? (
                    <p className="coAllocationNetLine muted" data-testid="allocation-net-worth-line">
                      Gross assets {formatMoney(grossAssets)} − liabilities {formatMoney(currentNetWorth.liabilities)} = net worth{" "}
                      {formatMoney(currentNetWorth.total)}
                    </p>
                  ) : null}
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
                <p className="coSignalMeta">What the cards owe, taken off the net worth above.</p>
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
                    className={`coSegmentedBtn${shownHoldingsView === "holdings" ? " coSegmentedBtnActive" : ""}`}
                    onClick={() => setHoldingsView("holdings")}
                  >
                    Holdings
                  </button>
                  <button
                    type="button"
                    className={`coSegmentedBtn${shownHoldingsView === "movers" ? " coSegmentedBtnActive" : ""}`}
                    onClick={() => setHoldingsView("movers")}
                  >
                    Movers
                  </button>
                  {/* Today's movers are live only: no Today tab on a past month. */}
                  {isLive ? (
                    <button
                      type="button"
                      className={`coSegmentedBtn${shownHoldingsView === "today" ? " coSegmentedBtnActive" : ""}`}
                      onClick={() => setHoldingsView("today")}
                    >
                      Today
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="coHoldingsList">
                {summaryRes.isLoading ? (
                  <p className="muted" role="status">Loading holdings…</p>
                ) : shownHoldingsView !== "today" && summaryRes.error && !summary ? (
                  <LoadError compact title="Couldn't load positions" error={summaryRes.error} onRetry={retry(summaryRes)} />
                ) : shownHoldingsView === "holdings" ? (
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
                ) : shownHoldingsView === "movers" ? (
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
                              ? `vs ${fmt.formatMonth(row.compare_month, "medium")}`
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
                          <span
                            className="coHoldingPct"
                            title={
                              row.compare_price_fallback
                                ? `Compared with its statement price of ${fmt.formatDate(row.compare_price_as_of)}`
                                : undefined
                            }
                          >
                            {row.delta_pct == null
                              ? "—"
                              : fmt.formatPercent(row.delta_pct, { signed: true })}
                            {row.compare_price_fallback ? " *" : ""}
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
                {shownHoldingsView === "today" && sinceUpdateBasisText ? (
                  <p className="coHoldingsNote">
                    {sinceUpdateBasisText}
                    {todayFallbackShown && sinceUpdate?.compare_basis?.price_date
                      ? ` * No quote on or before ${fmt.formatDate(sinceUpdate.compare_basis.price_date)}: compared with its own, older statement price.`
                      : ""}
                  </p>
                ) : null}
              </div>
            </article>
          </section>
        </RefreshingRegion>
      ) : null}
    </PageShell>
  );
}
