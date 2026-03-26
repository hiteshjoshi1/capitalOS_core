import "../App.css";
import PageShell from "../components/PageShell";

export default function WealthOverview() {
  return (
    <PageShell title="Wealth Overview" subtitle="Portfolio analytics — coming soon">
      <div className="wrap">
        <div className="card placeholderCard">
          <div className="cardTitle">Wealth Overview</div>
          <p className="muted">
            Detailed portfolio analytics (geography, platform allocation, risk
            concentration) will appear here in a future release.
          </p>
          <p className="muted">
            Navigate to specific sections (Stocks, Crypto, Cash) for current
            data.
          </p>
        </div>
      </div>
    </PageShell>
  );
}
