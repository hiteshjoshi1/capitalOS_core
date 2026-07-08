import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { DividendCompanyItem, DividendsByCompany, DividendsSummary, ExpectedDividendCompany, ExpectedDividendsOverview } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import HeroMetricCard from "../components/HeroMetricCard";
import TrendBarChart from "../components/TrendBarChart";
import SegmentedToggle from "../components/SegmentedToggle";

type LoadState = "idle" | "loading" | "ready" | "error";
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
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [monthSummary, setMonthSummary] = useState<DividendsSummary | null>(null);
  const [companySummary, setCompanySummary] = useState<DividendsByCompany | null>(null);
  const [expectedOverview, setExpectedOverview] = useState<ExpectedDividendsOverview | null>(null);
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency, setBaseCurrency] = useState<string>("SGD");
  const [companyTab, setCompanyTab] = useState<CompanyTab>("realized");

  const fromMonth = useMemo(() => shiftMonth(month, -11), [month]);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        setErr("");
        const [monthData, companyData, expectedData] = await Promise.all([
          api.dividendsSummary(fromMonth, month, "month", baseCurrency),
          api.dividendsByCompany(month, month, baseCurrency),
          api.expectedDividendsOverview(fromMonth, month, baseCurrency),
        ]);
        setMonthSummary(monthData);
        setCompanySummary(companyData);
        setExpectedOverview(expectedData);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, [fromMonth, month, baseCurrency]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatCompactMoney = (value?: number | null) =>
    value == null
      ? "—"
      : `${currencyPrefix} ${value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })}`;
  const formatNumber = (value?: number, maximumFractionDigits = 4) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString(undefined, { maximumFractionDigits })
      : "—";

  const topCompanies: DividendCompanyItem[] = (companySummary?.items ?? []).slice(0, 20);
  const expectedCompanies: ExpectedDividendCompany[] = expectedOverview?.companies ?? [];
  const monthKey = month;
  const yearKey = month.slice(0, 4);
  const quarterKey = (() => {
    const parts = month.split("-");
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
  const realizedBuckets = monthSummary?.buckets ?? [];
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
  const realizedPrevMonth = sumRealized((bucket) => bucket.bucket === shiftMonth(month, -1));
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
    [realizedBuckets, currencyPrefix],
  );

  return (
    <PageShell
      title="Dividends"
      subtitle="Realized cash-hit dividends + annualized expected dividends from holdings yield."
      activeRoute="/dividends"
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
            eyebrow="REALIZED THIS MONTH"
            value={formatMoney(realizedMonth.payout_minus_tax)}
            deltaChip={{
              text: `${momDeltaAbs >= 0 ? "+" : "-"}${momDeltaPct == null ? "—" : Math.abs(momDeltaPct * 100).toFixed(1) + "%"}`,
              positive: momDeltaAbs >= 0,
            }}
            insightText={`Gross ${formatMoney(realizedMonth.gross)} · Withholding ${formatMoney(realizedMonth.withholding)}`}
            deltaRow={[
              { label: "QUARTER-TO-DATE", value: formatMoney(realizedQuarter.payout_minus_tax), positive: true },
              { label: "YEAR-TO-DATE", value: formatMoney(realizedYear.payout_minus_tax), positive: true },
            ]}
          />

          <section className="grid g-mid">
            <div className="card">
              <h2>Expected, next 12 months</h2>
              <div className="big small">{formatMoney(expectedYear.payout_minus_tax)}</div>
              <div className={expectedVsTrailingPct != null && expectedVsTrailingPct >= 0 ? "good" : "bad"}>
                {expectedVsTrailingPct == null ? "—" : `${expectedVsTrailingPct >= 0 ? "+" : "-"}${Math.abs(expectedVsTrailingPct * 100).toFixed(0)}%`} vs trailing 12mo
              </div>
            </div>
            <div className="card">
              <h2>Portfolio coverage</h2>
              <div className="big small">
                {expectedOverview?.assets_with_actions ?? 0}/{expectedOverview?.holdings_considered ?? 0}
              </div>
              <div className="muted">holdings paying · {avgYieldPct == null ? "—" : `${avgYieldPct.toFixed(1)}%`} avg yield</div>
            </div>
          </section>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>12-month dividend income</h2>
              <div className="muted stockHoldingsMeta">Trailing total {formatMoney(realizedTrailing12.payout_minus_tax)}</div>
            </div>
            {trendPoints.length === 0 ? (
              <div className="muted">No dividends in selected range.</div>
            ) : (
              <TrendBarChart points={trendPoints} ariaLabel="12-month dividend income" />
            )}
          </div>

          <div className="card">
            <div className="stockHoldingsHeader">
              <h2>{companyTab === "realized" ? "Who paid you this month" : "Projected annual payers"}</h2>
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
            <div className="listRows">
              {companyTab === "realized" ? (
                topCompanies.length === 0 ? (
                  <div className="muted">No company-level dividend records yet.</div>
                ) : (
                  topCompanies.map((item) => (
                    <div className="listRow" key={`${item.asset_id ?? "na"}-${item.company}`}>
                      <div className="listRowMain">
                        <span className="listRowTitle">
                          {item.company}
                          {item.yield_pct != null ? <span className="tag">{item.yield_pct.toFixed(2)}%</span> : null}
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
                        {item.yield_pct != null ? <span className="tag">{item.yield_pct.toFixed(2)}%</span> : null}
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
        </div>
      )}
    </PageShell>
  );
}
