import "../App.css";
import PageShell from "../components/PageShell";

type PreviewCompany = {
  name: string;
  ticker: string;
  tag: string;
};

const PREVIEW_COMPANIES: PreviewCompany[] = [
  { name: "DBS Group Holdings", ticker: "SGX: D05", tag: "Snapshot draft" },
  { name: "Apple Inc.", ticker: "NASDAQ: AAPL", tag: "Thesis tracked" },
  { name: "Sea Limited", ticker: "NYSE: SE", tag: "Watchlist" },
];

export default function Companies() {
  return (
    <PageShell title="Companies" subtitle="Company research — coming soon.">
      <div className="dashboardWrap">
        <section className="card researchHeroCard">
          <span className="researchHeroEyebrowPill">Coming soon</span>
          <h2 className="researchHeroHeadline">Structured dossiers for every company you research.</h2>
          <p className="muted researchHeroDescription">
            This will become the dedicated home for company snapshots, thesis tracking, and long-form research
            workups — pulled from the same corpus AI Sage and Author Library already draw on.
          </p>
          <button className="btn btnLarge researchHeroCta" type="button" disabled>
            Companies — Coming Soon
          </button>
        </section>

        <section>
          <div className="researchSectionHeader">
            <p className="researchSectionLabel">Preview</p>
            <h2 className="researchSectionHeading">What's planned</h2>
          </div>
          <div className="researchPreviewGrid">
            {PREVIEW_COMPANIES.map((company) => (
              <article className="researchPreviewCard" key={company.ticker}>
                <div className="researchPreviewCardHeader">
                  <span className="researchPreviewCardIcon" aria-hidden="true" />
                  <div className="researchPreviewCardHeaderText">
                    <strong className="researchPreviewCardName">{company.name}</strong>
                    <span className="muted researchPreviewCardTicker">{company.ticker}</span>
                  </div>
                </div>
                <span className="researchPreviewSkeletonBar" aria-hidden="true" />
                <span className="researchPreviewSkeletonBar researchPreviewSkeletonBarShort" aria-hidden="true" />
                <span className="muted researchPreviewCardTag">{company.tag}</span>
              </article>
            ))}
          </div>
        </section>
      </div>
    </PageShell>
  );
}
