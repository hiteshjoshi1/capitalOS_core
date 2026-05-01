import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";

export default function LiabilitiesOverview() {
  return (
    <PageShell
      title="Liabilities Overview"
      subtitle="Organize revolving balances, installment debt, and payoff workflows."
    >
      <section className="grid sectionOverviewGrid">
        <article className="card sectionOverviewCard">
          <p className="sectionOverviewEyebrow">Overview</p>
          <h2 className="sectionOverviewTitle">Keep repayment pressure visible.</h2>
          <p className="muted">
            Use Credit Cards and Loans to inspect balances, due dates, and liability classes without reworking the detail pages.
          </p>
        </article>

        <Link className="card sectionOverviewLinkCard" to="/credit-cards">
          <p className="sectionOverviewEyebrow">Credit Cards</p>
          <h2 className="sectionOverviewTitle">Open the current card spend and utilization view.</h2>
          <p className="muted">Review card breakdowns, top purchases, recurring payments, and transaction detail.</p>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/loans">
          <p className="sectionOverviewEyebrow">Loans</p>
          <h2 className="sectionOverviewTitle">Track secured and installment debt.</h2>
          <p className="muted">Loan tracking remains lightly styled here and can be expanded in a later issue.</p>
        </Link>
      </section>
    </PageShell>
  );
}
