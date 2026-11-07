import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { monthEndCloseDate, useSelectedMonth } from "../lib/selectedMonth";
import { resourceKey, useApiResource } from "../lib/useApiResource";
import RefreshingRegion from "../components/RefreshingRegion";
import * as fmt from "../lib/format";
import { formatPlatformLabel } from "../lib/platformLabels";
import {
  buildCurrencyExposureRows,
  buildTopNDistribution,
  computeLargestPositionRisk,
  computePlatformConcentrationRisk,
  computeTopNConcentrationRisk,
  concentrationState,
  formatLargestPosition,
  formatRiskPercent,
  resolveRiskThresholds,
  RISK_THRESHOLDS_RESOURCE_KEY,
  riskStateClassName,
  thresholdRule,
  type TopN,
} from "../lib/risk";
import "../App.css";
import GeographyPieCard from "../components/dashboard/GeographyPieCard";
import MonthControl from "../components/MonthControl";
import PageShell from "../components/PageShell";
import SegmentedToggle from "../components/SegmentedToggle";
import { useBaseCurrency } from "../context/CurrencyContext";
import BaseCurrencyPicker from "../components/BaseCurrencyPicker";
import LoadError from "../components/LoadError";

/** Bar width as a share of the widest bar in its list (negative values draw none). */
function barWidth(value: number, widest: number): string {
  return `${widest > 0 ? Math.max(value, 0) / widest * 100 : 0}%`;
}

export default function WealthRisk() {
  const [month, setMonth] = useSelectedMonth();
  const [baseCurrency] = useBaseCurrency();
  const [selectedTopN, setSelectedTopN] = useState<TopN>(5);
  // #149: the lean /dashboard/risk-summary (net worth and positions, the same values as
  // /dashboard/summary) instead of the whole Overview summary.
  const summaryRes = useApiResource(resourceKey("riskSummary", month, baseCurrency), () =>
    api.riskSummary(month, baseCurrency),
  );
  const geographyRes = useApiResource(resourceKey("geographyExposure", month, baseCurrency), () =>
    api.dashboardGeographyExposure(month, baseCurrency),
  );
  // #253: the user's thresholds (Settings → Risk thresholds); the defaults until they
  // load, and if they can't.
  const thresholdsRes = useApiResource(RISK_THRESHOLDS_RESOURCE_KEY, () => api.riskThresholds());
  const thresholds = resolveRiskThresholds(thresholdsRes.data);
  const summary = summaryRes.data ?? null;
  const geographyExposure = geographyRes.data ?? null;
  const loadError = summaryRes.error ?? geographyRes.error;
  const selectedBaseCurrency = baseCurrency || summary?.base_currency || "SGD";

  // The currency the shown numbers are in (the previous one while a switch loads).
  const shownCurrency = summary?.base_currency || selectedBaseCurrency;
  const formatMoney = (value?: number | null) => fmt.formatMoney(value, shownCurrency);

  // #241: one point in time per month. The shares divide by the net worth at the
  // positions' point: live for the open month (the Overview headline), else that month-end.
  const netWorth = summary?.view_net_worth ?? summary?.net_worth ?? null;
  const netWorthTotal = netWorth?.total ?? 0;
  const cashPct = netWorthTotal ? ((netWorth?.cash ?? 0) / netWorthTotal) * 100 : 0;
  const closeDate = monthEndCloseDate(summary?.net_worth_boundary_at);
  const basisLabel = !summary
    ? null
    : summary.is_live
      ? "Live"
      : closeDate
        ? `As of ${fmt.formatDate(closeDate)} close`
        : "Month-end snapshot";

  // #253: every asset class, the same positions in the same order as Overview's
  // "Largest positions".
  const holdings = summary?.top_holdings ?? [];
  const riskLargest = computeLargestPositionRisk(holdings, netWorthTotal, thresholds.largestPositionWarnPct);
  const riskTopN = computeTopNConcentrationRisk(holdings, netWorthTotal, selectedTopN, thresholds.topNWarnPct);
  const topNDistribution = buildTopNDistribution(holdings, netWorthTotal, selectedTopN);
  const largestDisplayedPercent = Math.max(...topNDistribution.map((item) => item.percent), 0);

  const currencyRows = buildCurrencyExposureRows(summary?.currency_exposure?.items);
  const widestCurrency = Math.max(...currencyRows.map((row) => row.value), 0);
  const platformItems = summary?.platform_concentration?.items ?? [];
  const riskPlatform = computePlatformConcentrationRisk(summary?.platform_concentration, thresholds.platformWarnPct);
  const widestPlatform = Math.max(...platformItems.map((item) => item.value), 0);

  const settingsLink = <Link to="/settings">Change in Settings</Link>;

  return (
    <PageShell
      title="Wealth Risk"
      subtitle={`Concentration signals and exposure${basisLabel ? ` · ${basisLabel}` : ""}.`}
      headerActions={(
        <>
          <MonthControl month={month} onMonthChange={setMonth} />
          <BaseCurrencyPicker />
        </>
      )}
    >
      {summaryRes.isLoading && !loadError ? <div className="card" role="status">Loading…</div> : null}
      {loadError ? (
        <LoadError title="Couldn't load risk" error={loadError.message} onRetry={() => { void summaryRes.reload().catch(() => undefined); void geographyRes.reload().catch(() => undefined); }} />
      ) : null}

      {summary ? (
        <RefreshingRegion className="wealthOverviewLayout" busy={summaryRes.isFetching || geographyRes.isFetching}>
          <section className="grid g-mid">
            <div className="card">
              <h2>Cash buffer</h2>
              <div className="big small">{fmt.formatPercent(cashPct, { scale: "points" })}</div>
              <div className="muted">{formatMoney(netWorth?.cash)} of {formatMoney(netWorthTotal)} net worth</div>
            </div>

            <div className="card">
              <h2>Largest position</h2>
              <div className={`big small ${riskStateClassName(riskLargest.state)}`}>{formatLargestPosition(riskLargest)}</div>
              {riskLargest.hasData ? (
                <div className="muted">{riskLargest.assetClass} · {formatMoney(riskLargest.value)}</div>
              ) : null}
              <div className="muted riskThresholdRule">
                <span className={riskStateClassName(riskLargest.state)}>{thresholdRule(thresholds.largestPositionWarnPct)}</span>
                {" · "}
                {settingsLink}
              </div>
            </div>

            <div className="card">
              <div className="stockHoldingsHeader">
                <h2>{`Top ${selectedTopN} concentration`}</h2>
                <SegmentedToggle
                  ariaLabel="Top N positions"
                  value={selectedTopN === 3 ? "3" : "5"}
                  onChange={(v) => setSelectedTopN(v === "3" ? 3 : 5)}
                  options={[
                    { value: "3", label: "Top 3" },
                    { value: "5", label: "Top 5" },
                  ]}
                />
              </div>
              <div className={`big small ${riskStateClassName(riskTopN.state)}`}>{formatRiskPercent(riskTopN.percent)}</div>
              <div className="muted riskThresholdRule">
                <span className={riskStateClassName(riskTopN.state)}>{thresholdRule(thresholds.topNWarnPct)}</span>
                {" · "}
                {settingsLink}
              </div>
              {!riskTopN.hasFullSelection && riskTopN.hasData ? (
                <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                  {`Showing ${riskTopN.availableCount} of requested ${riskTopN.selectedN} positions.`}
                </div>
              ) : null}
            </div>
          </section>

          <section className="card riskPositionsCard">
            <div className="riskSectionHeader">
              <div>
                <div className="riskSectionEyebrow">Concentration</div>
                <h2>Where the top positions sit</h2>
              </div>
              <div className="muted stockHoldingsMeta">Share of total net worth · stocks, funds and crypto</div>
            </div>
            {topNDistribution.length > 0 ? (
              <ul className="riskChartList">
                {topNDistribution.map((item) => (
                  <li className="riskChartRow" key={`${item.symbol}-${item.assetClass}`}>
                    <span className="riskChartIdentity">
                      <strong className="riskChartSymbol">{item.symbol}</strong>
                      <span className="riskChartMeta">{item.assetClass} · {formatMoney(item.value)}</span>
                    </span>
                    <div className="riskChartTrack">
                      <span
                        className="riskChartFill"
                        style={{ width: `${largestDisplayedPercent > 0 ? (item.percent / largestDisplayedPercent) * 100 : 0}%` }}
                        title={`${item.symbol}: ${formatRiskPercent(item.percent)}`}
                      ></span>
                    </div>
                    <strong className="riskChartPercent">{formatRiskPercent(item.percent)}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="riskNoData">No holdings concentration data for this month or net worth is not positive.</div>
            )}
          </section>

          <section className="card riskPositionsCard" aria-label="Currency exposure">
            <div className="riskSectionHeader">
              <div>
                <div className="riskSectionEyebrow">Currency exposure</div>
                <h2>What the net worth is held in</h2>
              </div>
              <div className="muted stockHoldingsMeta">Share of total net worth · stablecoins count as USD</div>
            </div>
            {currencyRows.length > 0 && netWorthTotal > 0 ? (
              <ul className="riskChartList">
                {currencyRows.map((row) => (
                  <li className="riskChartRow" key={row.currency}>
                    <span className="riskChartIdentity">
                      <strong className="riskChartSymbol">{row.label}</strong>
                      <span className="riskChartMeta">
                        {row.parts.map((part) => `${part.label} ${formatMoney(part.key === "liabilities" ? -part.value : part.value)}`).join(" · ")}
                      </span>
                    </span>
                    <div className="riskChartTrack">
                      <span
                        className="riskChartFill"
                        style={{ width: barWidth(row.value, widestCurrency) }}
                        title={`${row.label}: ${formatRiskPercent(row.percent)}`}
                      ></span>
                    </div>
                    <strong className="riskChartPercent">{formatRiskPercent(row.percent)}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="riskNoData">No currency exposure for this month or net worth is not positive.</div>
            )}
          </section>

          <section className="card riskPositionsCard" aria-label="Platform concentration">
            <div className="riskSectionHeader">
              <div>
                <div className="riskSectionEyebrow">Platform concentration</div>
                <h2>Where the assets are held</h2>
              </div>
              <div className="muted stockHoldingsMeta">
                Share of gross assets, as Overview&apos;s platform split ·{" "}
                <span className={riskStateClassName(riskPlatform.state)}>{thresholdRule(thresholds.platformWarnPct)}</span>
              </div>
            </div>
            {platformItems.length > 0 ? (
              <ul className="riskChartList">
                {platformItems.map((item) => {
                  const state = riskStateClassName(concentrationState(item.percent, thresholds.platformWarnPct));
                  return (
                    <li className="riskChartRow" key={`${item.platform}-${item.platform_type ?? ""}-${item.country ?? ""}`}>
                      <span className="riskChartIdentity">
                        <strong className="riskChartSymbol">{formatPlatformLabel(item.platform)}</strong>
                        <span className="riskChartMeta">{formatMoney(item.value)}</span>
                      </span>
                      <div className="riskChartTrack">
                        <span
                          className="riskChartFill"
                          style={{ width: barWidth(item.value, widestPlatform) }}
                          title={`${formatPlatformLabel(item.platform)}: ${formatRiskPercent(item.percent)}`}
                        ></span>
                      </div>
                      <strong className={`riskChartPercent ${state}`}>{formatRiskPercent(item.percent)}</strong>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="riskNoData">No platform data for this month.</div>
            )}
          </section>

          <GeographyPieCard exposure={geographyExposure} formatMoney={formatMoney} />
        </RefreshingRegion>
      ) : null}
    </PageShell>
  );
}
