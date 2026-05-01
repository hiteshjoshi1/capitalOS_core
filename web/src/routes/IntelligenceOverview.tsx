import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";

export default function IntelligenceOverview() {
  return (
    <PageShell
      title="Intelligence Overview"
      subtitle="Move between AI guidance, author research, and company workups from one section."
    >
      <section className="grid sectionOverviewGrid">
        <article className="card sectionOverviewCard">
          <p className="sectionOverviewEyebrow">Overview</p>
          <h2 className="sectionOverviewTitle">Research and synthesis stay connected.</h2>
          <p className="muted">
            The section tabs keep AI Sage, Author Library, and Companies grouped without changing their underlying page logic.
          </p>
        </article>

        <Link className="card sectionOverviewLinkCard" to="/ai-sage">
          <p className="sectionOverviewEyebrow">AI Sage</p>
          <h2 className="sectionOverviewTitle">Query grounded business and investing context.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/author-library">
          <p className="sectionOverviewEyebrow">Author Library</p>
          <h2 className="sectionOverviewTitle">Browse authors, documents, and curated passages.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/companies">
          <p className="sectionOverviewEyebrow">Companies</p>
          <h2 className="sectionOverviewTitle">Keep company research accessible as a dedicated tab.</h2>
        </Link>
      </section>
    </PageShell>
  );
}
