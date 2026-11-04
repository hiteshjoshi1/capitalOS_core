import { useCallback, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { DividendCompanyItem, DividendsSummary, ExpectedDividendCompany } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import FxNote from "../components/FxNote";
import HeroMetricCard from "../components/HeroMetricCard";
import TrendBarChart from "../components/TrendBarChart";
import SegmentedToggle from "../components/SegmentedToggle";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";

type CompanyTab = "realized" | "expected";

function shiftMonth(month: string, delta: number): string {
  const [yearRaw, monthRaw] = month.split("-");
  const year = Number(yearRaw);
  const monthIndex = Number(monthRaw) - 1;
  const dt = new Date(Date.UTC(year, monthIndex + delta, 1));
  const nextYear = dt.getUTCFullYear();
  const nextMonth = String(dt.getUTCMonth() + 1).padStart(2, "0");
  return `${nextYear}-${nextMonth}`;
}

export default function Dividends() {
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency] = useBaseCurrency();
  const [companyTab, setCompanyTab] = useState<CompanyTab>("realized");

  const fromMonth = useMemo(() => shiftMonth(month, -11), [month]);

  // #148: three independent resources. The page renders once the monthly summary is in;
  // the company and expected sections show their own loading/error state.
  const monthRes = useApiResource(resourceKey("dividendsSummary", fromMonth, month, baseCurrency), () =>
    api.dividendsSummary(fromMonth, month, "month", baseCurrency),
  );
  const companyRes = useApiResource(resourceKey("dividendsByCompany", month, baseCurrency), () =>
    api.dividendsByCompany(month, month, baseCurrency),
  );
  const expectedRes = useApiResource(resourceKey("expectedDividends", fromMonth, month, baseCurrency), () =>
    api.expectedDividendsOverview(fromMonth, month, baseCurrency),
  );
  const monthSummary = monthRes.data ?? null;
  const companySummary = companyRes.data ?? null;
  const expectedOverview = expectedRes.data ?? null;
  // Derive periods from the month the summary is for: while the next month loads, the
  // previous month's summary stays on screen and must be read as that month.
  const shownMonth = monthSummary?.to_month || month;

  const shownCurrency = monthSummary?.base_currency || baseCurrency;
  const formatMoney = useCallback((value?: number | null) => fmt.formatMoney(value, shownCurrency), [shownCurrency]);
  const formatCompactMoney = useCallback(
    (value?: number | null) => fmt.formatMoneyCompact(value, shownCurrency),
    [shownCurrency],
  );
  const formatNumber = (value?: number) => fmt.formatNumber(value, 4);

  const topCompanies: DividendCompanyItem[] = (companySummary?.items ?? []).slice(0, 20);
  const expectedCompanies: ExpectedDividendCompany[] = useMemo(
    () => expectedOverview?.companies ?? [],
    [expectedOverview?.companies],
  );
  const monthKey = shownMonth;
  const yearKey = shownMonth.slice(0, 4);
  const quarterKey = (() => {
    const parts = shownMonth.split("-");
    const year = parts[0] ?? "";
    const monthNumber = Number(parts[1] ?? "1");
    const quarter = Math.floor((Math.max(1, monthNumber) - 1) / 3) + 1;
    return `${year}-Q${quarter}`;
  })();
  const toQuarterKey = (bucket: string) => {
    const parts = bucket.split("-");
    const year = parts[0] ?? "";
    const monthNumber = Number(parts[1] ?? "1");
    const quarter = Math.floor((Math.max(1, monthNumber) - 1) / 3) + 1;
    return `${year}-Q${quarter}`;
  };
  const realizedBuckets = useMemo(() => monthSummary?.buckets ?? [], [monthSummary?.buckets]);
  const sumRealized = (predicate: (bucket: DividendsSummary["buckets"][number]) => boolean) =>
    realizedBuckets
      .filter(predicate)
      .reduce(
        (acc, bucket) => ({
          gross: acc.gross + bucket.gross,
          withholding: acc.withholding + bucket.withholding,
          net_received: acc.net_received + bucket.net_received,
          payout_minus_tax: acc.payout_minus_tax + bucket.payout_minus_tax,
        }),
        { gross: 0, withholding: 0, net_received: 0, payout_minus_tax: 0 },
      );
  const realizedMonth = sumRealized((bucket) => bucket.bucket === monthKey);
  const realizedPrevMonth = sumRealized((bucket) => bucket.bucket === shiftMonth(shownMonth, -1));
  const realizedQuarter = sumRealized((bucket) => toQuarterKey(bucket.bucket) === quarterKey);
  const realizedYear = sumRealized((bucket) => bucket.bucket.startsWith(`${yearKey}-`));
  const realizedTrailing12 = sumRealized(() => true);

  const expectedYear = expectedOverview?.yearly ?? { gross: 0, estimated_tax: 0, payout_minus_tax: 0 };

  const avgYieldPct = useMemo(() => {
    const withYield = expectedCompanies.filter((c) => c.yield_pct != null);
    if (withYield.length === 0) return null;
    return withYield.reduce((acc, c) => acc + (c.yield_pct ?? 0), 0) / withYield.length;
  }, [expectedCompanies]);

  const momDeltaAbs = realizedMonth.payout_minus_tax - realizedPrevMonth.payout_minus_tax;
  const momDeltaPct = realizedPrevMonth.payout_minus_tax !== 0 ? momDeltaAbs / Math.abs(realizedPrevMonth.payout_minus_tax) : null;
  const expectedVsTrailingPct =
    realizedTrailing12.payout_minus_tax !== 0
      ? (expectedYear.payout_minus_tax - realizedTrailing12.payout_minus_tax) / Math.abs(realizedTrailing12.payout_minus_tax)
      : null;

  const trendPoints = useMemo(
    () =>
      realizedBuckets.map((bucket) => ({
        month: bucket.bucket,
        value: bucket.payout_minus_tax,
        displayValue: formatCompactMoney(bucket.payout_minus_tax),
        tone: "neutral" as const,
      })),
    [realizedBuckets, formatCompactMoney],
  );

  return (
    <PageShell
      title="Dividends"
      subtitle="Cash dividends received, and what your holdings are projected to pay next."
      activeRoute="/dividends"
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <BaseCurrencyPicker />
        </>
      )}
    >
      {monthRes.isLoading && <div className="card">Loading…</div>}
      {monthRes.error && (
        <div className="card error">
          <div className="cardTitle">API error</div>
          <pre className="pre">{monthRes.error.message}</pre>
        </div>
      )}

      {monthSummary && (
        <RefreshingRegion
          className="wealthOverviewLayout"
          busy={monthRes.isFetching || companyRes.isFetching || expectedRes.isFetching}
        >
          <HeroMetricCard
            eyebrow="REALIZED THIS MONTH"
            value={formatMoney(realizedMonth.payout_minus_tax)}
            deltaChip={{
              // No baseline is "—", not "+—" (#131).
              text: fmt.formatPercent(momDeltaPct, { signed: true }),
              positive: momDeltaAbs >= 0,
            }}
            insightText={`Gross ${formatMoney(realizedMonth.gross)} · Withholding ${formatMoney(realizedMonth.withholding)}`}
            deltaRow={[
              { label: "QUARTER-TO-DATE", value: formatMoney(realizedQuarter.payout_minus_tax), positive: true },
              { label: "YEAR-TO-DATE", value: formatMoney(realizedYear.payout_minus_tax), positive: true },
            ]}
          />
          <FxNote sources={[monthSummary, companySummary]} />

          <section aria-labelledby="dividend-signals-heading">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">SIGNALS</p>
                <h2 className="coSectionTitle" id="dividend-signals-heading">What's received vs. what's ahead</h2>
              </div>
            </div>
            <div className="dividendSignalGrid">
              <article className="card dividendSignalCard">
                <p className="dividendSignalLabel">Expected, next 12 months</p>
                {expectedRes.error ? (
                  <p className="dividendSignalContext">Couldn't load expected dividends: {expectedRes.error.message}</p>
                ) : null}
                <p className="dividendSignalValue">{expectedOverview ? formatMoney(expectedYear.payout_minus_tax) : "—"}</p>
                <p className="dividendSignalContext">
                  <span className={fmt.directionClass(expectedVsTrailingPct)}>
                    {fmt.formatPercent(expectedVsTrailingPct, { signed: true, decimals: 0 })}
                  </span>{" "}
                  vs trailing 12 months ({formatMoney(realizedTrailing12.payout_minus_tax)}), based on current holdings and yields.
                </p>
              </article>
              <article className="card dividendSignalCard">
                <p className="dividendSignalLabel">Portfolio coverage</p>
                <p className="dividendSignalValue">
                  {expectedOverview?.assets_with_actions ?? 0} / {expectedOverview?.holdings_considered ?? 0}
                </p>
                <p className="dividendSignalContext">
                  Holdings currently paying a dividend · {fmt.formatPercent(avgYieldPct, { scale: "points" })} average yield.
                </p>
              </article>
            </div>
          </section>

          <section className="dividendHistorySection" aria-labelledby="dividend-history-heading">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">HISTORY</p>
                <h2 className="coSectionTitle" id="dividend-history-heading">12-month dividend income</h2>
              </div>
              <div className="muted stockHoldingsMeta">Trailing total {formatMoney(realizedTrailing12.payout_minus_tax)}</div>
            </div>
            <div className="card dividendHistoryCard">
              {trendPoints.length === 0 ? (
                <div className="muted">No dividends in selected range.</div>
              ) : (
                <TrendBarChart points={trendPoints} ariaLabel="12-month dividend income" />
              )}
            </div>
          </section>

          <section aria-labelledby="dividend-companies-heading">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">COMPANIES</p>
                <h2 className="coSectionTitle" id="dividend-companies-heading">
                  {companyTab === "realized" ? "Who paid you this month" : "Projected annual payers"}
                </h2>
              </div>
              <SegmentedToggle
                ariaLabel="Realized or expected companies"
                value={companyTab}
                onChange={setCompanyTab}
                options={[
                  { value: "realized", label: "Realized" },
                  { value: "expected", label: "Expected" },
                ]}
              />
            </div>
            <div className="card dividendCompaniesCard">
              <p className="dividendCompaniesContext">
                {companyTab === "realized"
                  ? "Cash dividends received in the selected month, after withholding tax."
                  : "Annualized dividend estimates based on current holdings and available yields."}
              </p>
              <div className="listRows">
              {(companyTab === "realized" ? companyRes : expectedRes).error ? (
                <div className="muted" role="alert">
                  Couldn't load companies: {(companyTab === "realized" ? companyRes : expectedRes).error?.message}
                </div>
              ) : (companyTab === "realized" ? companySummary : expectedOverview) == null ? (
                <div className="muted">Loading…</div>
              ) : companyTab === "realized" ? (
                topCompanies.length === 0 ? (
                  <div className="muted">No company-level dividend records yet.</div>
                ) : (
                  topCompanies.map((item) => (
                    <div className="listRow" key={`${item.asset_id ?? "na"}-${item.company}`}>
                      <div className="listRowMain">
                        <span className="listRowTitle">
                          {item.company}
                          {item.yield_pct != null ? <span className="tag">{fmt.formatPercent(item.yield_pct, { scale: "points", decimals: 2 })}</span> : null}
                        </span>
                        <span className="listRowMeta">
                          <span>{item.symbol ?? "—"}</span>
                          <span>{item.country ?? "—"}</span>
                        </span>
                      </div>
                      <div className="listRowValue good">
                        {formatMoney(item.payout_minus_tax)}
                        <span className="listRowValueSecondary muted">
                          Gross {formatMoney(item.gross)} · WHT {formatMoney(item.withholding)}
                        </span>
                      </div>
                    </div>
                  ))
                )
              ) : expectedCompanies.length === 0 ? (
                <div className="muted">No expected dividend estimates found for selected range.</div>
              ) : (
                expectedCompanies.map((item) => (
                  <div className="listRow" key={`${item.asset_id}-${item.symbol}`}>
                    <div className="listRowMain">
                      <span className="listRowTitle">
                        {item.company}
                        {item.yield_pct != null ? <span className="tag">{fmt.formatPercent(item.yield_pct, { scale: "points", decimals: 2 })}</span> : null}
                      </span>
                      <span className="listRowMeta">
                        <span>{item.symbol}</span>
                        <span>{formatNumber(item.shares)} shares</span>
                      </span>
                    </div>
                    <div className="listRowValue good">
                      {formatMoney(item.yearly_dividend)}
                      <span className="listRowValueSecondary muted">
                        Qtly {formatMoney(item.quarterly_dividend)} · Mthly {formatMoney(item.monthly_dividend)}
                      </span>
                    </div>
                  </div>
                ))
              )}
              </div>
            </div>
          </section>
        </RefreshingRegion>
      )}
    </PageShell>
  );
}
