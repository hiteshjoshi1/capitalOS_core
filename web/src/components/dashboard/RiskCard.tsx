import {
  formatLargestPosition,
  formatRiskPercent,
  riskStateClassName,
  RISK_LARGEST_POSITION_WARN_PCT,
  RISK_TOP5_TARGET_MAX_PCT,
  RISK_TOP5_TARGET_MIN_PCT,
} from "../../lib/risk";
import type { LargestPositionRisk, RiskDistributionItem, TopN, TopNConcentrationRisk } from "../../lib/risk";

type RiskCardProps = {
  riskLargest: LargestPositionRisk;
  riskTopN: TopNConcentrationRisk;
  selectedTopN: TopN;
  onSelectTopN: (value: TopN) => void;
  hasRiskDistribution: boolean;
  topNDistribution: RiskDistributionItem[];
  formatMoney: (value?: number, maximumFractionDigits?: number) => string;
  cashPercent: number;
};

export default function RiskCard({
  riskLargest,
  riskTopN,
  selectedTopN,
  onSelectTopN,
  hasRiskDistribution,
  topNDistribution,
  formatMoney,
  cashPercent,
}: RiskCardProps) {
  return (
    <div className="card riskCard">
      <h2>Risk</h2>
      <div className="kpi">
        <div className="label">Cash</div>
        <div className="val">{cashPercent.toFixed(1)}%</div>
        <div className="delta muted">% of net worth</div>
      </div>
      <div style={{ height: 10 }}></div>
      <div className="kpi">
        <div className="label">Largest position</div>
        <div className={`val ${riskStateClassName(riskLargest.state)}`}>{formatLargestPosition(riskLargest)}</div>
        <div className="delta">
          Concentration threshold:{" "}
          <span className={riskStateClassName(riskLargest.state)}>{RISK_LARGEST_POSITION_WARN_PCT}%</span>
        </div>
      </div>
      <div style={{ height: 10 }}></div>
      <div className="kpi">
        <div className="riskTopNHeader">
          <div className="label">{`Top ${selectedTopN} positions`}</div>
          <div className="riskTopNSegmented" role="group" aria-label="Top N positions">
            <button
              type="button"
              className={`riskTopNButton ${selectedTopN === 3 ? "active" : ""}`}
              aria-pressed={selectedTopN === 3}
              onClick={() => onSelectTopN(3)}
            >
              Top 3
            </button>
            <button
              type="button"
              className={`riskTopNButton ${selectedTopN === 5 ? "active" : ""}`}
              aria-pressed={selectedTopN === 5}
              onClick={() => onSelectTopN(5)}
            >
              Top 5
            </button>
          </div>
        </div>
        <div className={`val ${riskStateClassName(riskTopN.state)}`}>{formatRiskPercent(riskTopN.percent)}</div>
        <div className="delta">
          Target band: {RISK_TOP5_TARGET_MIN_PCT}–{RISK_TOP5_TARGET_MAX_PCT}%
        </div>
        {hasRiskDistribution ? (
          <div className="riskDistribution">
            <div className="riskChartWrap" aria-label={`Top ${selectedTopN} distribution chart`}>
              <ul className="riskChartList">
                {topNDistribution.map((item) => (
                  <li className="riskChartRow" key={`${item.symbol}-${item.assetClass}`}>
                    <span className="riskChartSymbol">{item.symbol}</span>
                    <div className="riskChartTrack">
                      <span
                        className="riskChartFill"
                        style={{ width: `${Math.min(100, item.percent)}%` }}
                        title={`${item.symbol}: ${formatRiskPercent(item.percent)}`}
                      ></span>
                    </div>
                    <span className="riskChartPercent">{formatRiskPercent(item.percent)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <table className="table riskTable" data-testid="risk-distribution-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Asset Class</th>
                  <th className="right">Value</th>
                  <th className="right">% of net worth</th>
                </tr>
              </thead>
              <tbody>
                {topNDistribution.map((item) => (
                  <tr key={item.symbol}>
                    <td>{item.symbol}</td>
                    <td>{item.assetClass}</td>
                    <td className="right">{formatMoney(item.value)}</td>
                    <td className="right">{formatRiskPercent(item.percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="riskNoData">No holdings concentration data for this month or net worth is not positive.</div>
        )}
        {!riskTopN.hasFullSelection && riskTopN.hasData ? (
          <div className="riskHelperText">{`Showing ${riskTopN.availableCount} of requested ${riskTopN.selectedN} positions.`}</div>
        ) : null}
      </div>
      {!riskLargest.hasData || !riskTopN.hasData ? (
        <div className="muted" style={{ marginTop: 12 }}>
          Insufficient holdings data for full risk concentration analysis.
        </div>
      ) : null}
    </div>
  );
}
