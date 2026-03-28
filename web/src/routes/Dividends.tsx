import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { DividendCompanyItem, DividendsByCompany, DividendsSummary, ExpectedDividendsOverview } from "../lib/api";
import { useSelectedMonth } from "../lib/selectedMonth";
import "../App.css";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

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
  const [assumedTaxRate, setAssumedTaxRate] = useState<string>("10");
  const [countryRates, setCountryRates] = useState<string>("US:15,IN:10,SG:0,HK:0");

  const fromMonth = useMemo(() => shiftMonth(month, -11), [month]);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        setErr("");
        const taxRateNumber = Number(assumedTaxRate || "0");
        const [monthData, companyData, expectedData] = await Promise.all([
          api.dividendsSummary(fromMonth, month, "month", baseCurrency, taxRateNumber, countryRates),
          api.dividendsByCompany(month, month, baseCurrency, taxRateNumber, countryRates),
          api.expectedDividendsOverview(fromMonth, month, baseCurrency, taxRateNumber, countryRates),
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
  }, [fromMonth, month, baseCurrency, assumedTaxRate, countryRates]);

  const currencyPrefix = baseCurrency === "SGD" ? "S$" : `${baseCurrency} `;
  const formatMoney = (value?: number, maximumFractionDigits = 0) =>
    value == null ? "—" : `${currencyPrefix} ${value.toLocaleString(undefined, { maximumFractionDigits })}`;
  const formatNumber = (value?: number, maximumFractionDigits = 4) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString(undefined, { maximumFractionDigits })
      : "—";

  const topCompanies: DividendCompanyItem[] = (companySummary?.items ?? []).slice(0, 20);
  const expectedCompanies = expectedOverview?.companies ?? [];
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
  const realizedQuarter = sumRealized((bucket) => toQuarterKey(bucket.bucket) === quarterKey);
  const realizedYear = sumRealized((bucket) => bucket.bucket.startsWith(`${yearKey}-`));

  const expectedMonth = expectedOverview?.monthly ?? { gross: 0, estimated_tax: 0, payout_minus_tax: 0 };
  const expectedQuarter = expectedOverview?.quarterly ?? { gross: 0, estimated_tax: 0, payout_minus_tax: 0 };
  const expectedYear = expectedOverview?.yearly ?? { gross: 0, estimated_tax: 0, payout_minus_tax: 0 };

  return (
    <PageShell
      title="Dividends"
      subtitle="Realized cash-hit dividends + annualized expected dividends from holdings yield."
      activeRoute="/dividends"
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <label className="pill">
            <span>Base</span>
            <select
              className="monthInput"
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
          <label className="pill">
            <span>Tax %</span>
            <input
              className="monthInput"
              aria-label="Assumed tax rate percent"
              value={assumedTaxRate}
              onChange={(e) => setAssumedTaxRate(e.target.value)}
              style={{ width: 64 }}
            />
          </label>
          <label className="pill">
            <span>Country Rates</span>
            <input
              className="monthInput"
              aria-label="Country tax rates"
              value={countryRates}
              onChange={(e) => setCountryRates(e.target.value)}
              style={{ width: 220 }}
            />
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
        <>
          <section className="grid g-mid">
            <div className="card">
              <h2>Realized (Selected Month)</h2>
              <div className="big small">{formatMoney(realizedMonth.payout_minus_tax)}</div>
              <div className="muted">Gross: {formatMoney(realizedMonth.gross)}</div>
              <div className="muted">Withholding: {formatMoney(realizedMonth.withholding)}</div>
              <div className="muted" style={{ marginTop: 4 }}>
                Quarter-to-date: {formatMoney(realizedQuarter.payout_minus_tax)} | Year-to-date: {formatMoney(realizedYear.payout_minus_tax)}
              </div>
            </div>
          </section>

          <section className="grid g-mid" style={{ marginTop: 16 }}>
            <div className="card">
              <h2>Monthly Buckets (Realized)</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th className="right">Gross</th>
                    <th className="right">Withholding</th>
                    <th className="right">Net</th>
                    <th className="right">Post-tax</th>
                  </tr>
                </thead>
                <tbody>
                  {(monthSummary?.buckets ?? []).map((bucket) => (
                    <tr key={bucket.bucket}>
                      <td>{bucket.bucket}</td>
                      <td className="right">{formatMoney(bucket.gross)}</td>
                      <td className="right">{formatMoney(bucket.withholding)}</td>
                      <td className="right">{formatMoney(bucket.net_received)}</td>
                      <td className="right">{formatMoney(bucket.payout_minus_tax)}</td>
                    </tr>
                  ))}
                  {monthSummary && monthSummary.buckets.length === 0 ? (
                    <tr>
                      <td className="muted" colSpan={5}>No dividends in selected range.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

            <div className="card">
              <h2>By Company (Realized, Selected Month)</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Symbol</th>
                    <th className="right">Gross</th>
                    <th className="right">Withholding</th>
                    <th className="right">Net</th>
                    <th className="right">Yield</th>
                  </tr>
                </thead>
                <tbody>
                  {topCompanies.map((item) => (
                    <tr key={`${item.asset_id ?? "na"}-${item.company}`}>
                      <td>{item.company}</td>
                      <td>{item.symbol}</td>
                      <td className="right">{formatMoney(item.gross)}</td>
                      <td className="right">{formatMoney(item.withholding)}</td>
                      <td className="right">{formatMoney(item.net_received)}</td>
                      <td className="right">{item.yield_pct == null ? "—" : `${item.yield_pct.toFixed(2)}%`}</td>
                    </tr>
                  ))}
                  {topCompanies.length === 0 ? (
                    <tr>
                      <td className="muted" colSpan={6}>No company-level dividend records yet.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="grid g-mid" style={{ marginTop: 16 }}>
            <div className="card">
              <h2>Expected Dividends (Holdings-Based)</h2>
              <div className="muted">
                Holdings considered: {expectedOverview?.holdings_considered ?? 0} | Assets estimated: {expectedOverview?.assets_with_actions ?? 0} | Yield snapshots used: {expectedOverview?.actions_evaluated ?? 0}
              </div>
              <table className="table" style={{ marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>Period</th>
                    <th className="right">Gross</th>
                    <th className="right">Estimated Tax</th>
                    <th className="right">After Tax</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Month</td>
                    <td className="right">{formatMoney(expectedMonth.gross)}</td>
                    <td className="right">{formatMoney(expectedMonth.estimated_tax)}</td>
                    <td className="right">{formatMoney(expectedMonth.payout_minus_tax)}</td>
                  </tr>
                  <tr>
                    <td>Quarter</td>
                    <td className="right">{formatMoney(expectedQuarter.gross)}</td>
                    <td className="right">{formatMoney(expectedQuarter.estimated_tax)}</td>
                    <td className="right">{formatMoney(expectedQuarter.payout_minus_tax)}</td>
                  </tr>
                  <tr>
                    <td>Year</td>
                    <td className="right">{formatMoney(expectedYear.gross)}</td>
                    <td className="right">{formatMoney(expectedYear.estimated_tax)}</td>
                    <td className="right">{formatMoney(expectedYear.payout_minus_tax)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="card">
              <h2>By Company (Expected)</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Symbol</th>
                    <th className="right">Shares</th>
                    <th className="right">Yield</th>
                    <th className="right">Price</th>
                    <th className="right">Yearly Dividend</th>
                    <th className="right">Quarterly Dividend</th>
                    <th className="right">Monthly Dividend</th>
                  </tr>
                </thead>
                <tbody>
                  {expectedCompanies.map((item) => (
                    <tr key={`${item.asset_id}-${item.symbol}`}>
                      <td>{item.company}</td>
                      <td>{item.symbol}</td>
                      <td className="right">{formatNumber(item.shares)}</td>
                      <td className="right">{item.yield_pct == null ? "—" : `${item.yield_pct.toFixed(2)}%`}</td>
                      <td className="right">
                        {item.price == null
                          ? "—"
                          : `${item.quote_currency ?? baseCurrency} ${formatNumber(item.price)}`}
                      </td>
                      <td className="right">{formatMoney(item.yearly_dividend)}</td>
                      <td className="right">{formatMoney(item.quarterly_dividend)}</td>
                      <td className="right">{formatMoney(item.monthly_dividend)}</td>
                    </tr>
                  ))}
                  {expectedCompanies.length === 0 ? (
                    <tr>
                      <td className="muted" colSpan={8}>No expected dividend estimates found for selected range.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </PageShell>
  );
}
