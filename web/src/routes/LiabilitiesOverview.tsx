import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";

export default function LiabilitiesOverview() {
  return (
    <PageShell
      title="Liabilities"
      subtitle="Organize revolving balances and repayment workflows from one section."
    >
      <section className="grid sectionOverviewGrid">
        <article className="card sectionOverviewCard sectionOverviewPrimaryCard">
          <p className="sectionOverviewEyebrow">Credit Cards</p>
          <h2 className="sectionOverviewTitle">Open the current card spend and utilization view.</h2>
          <p className="muted sectionOverviewDescription">
            Review card breakdowns, top purchases, recurring payments, and transaction detail in the existing credit card workspace.
          </p>
          <div className="sectionOverviewActions">
            <Link className="btn btnLarge sectionOverviewCta" to="/credit-cards">
              Open Credit Cards
            </Link>
          </div>
        </article>

        <article className="card sectionOverviewCard">
          <p className="sectionOverviewEyebrow">Loans</p>
          <h2 className="sectionOverviewTitle">Track secured and installment debt.</h2>
          <p className="muted sectionOverviewDescription">
            Loan tracking will stay lightweight for now and can be expanded in a later issue once the surrounding workflows are ready.
          </p>
          <div className="sectionOverviewActions">
            <button className="btn btnLarge sectionOverviewCta" type="button" disabled>
              Loans Coming Soon
            </button>
          </div>
        </article>
      </section>
    </PageShell>
  );
}
