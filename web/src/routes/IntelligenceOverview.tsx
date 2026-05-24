import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";

export default function IntelligenceOverview() {
  return (
    <PageShell
      title="Research"
      subtitle="Move between AI guidance, author research, and future company workups from one section."
    >
      <section className="grid sectionOverviewGrid">
        <article className="card sectionOverviewCard sectionOverviewPrimaryCard">
          <p className="sectionOverviewEyebrow">AI Sage</p>
          <h2 className="sectionOverviewTitle">Query grounded business and investing context.</h2>
          <p className="muted sectionOverviewDescription">
            Ask questions across your corpus and current research stack, then inspect ranked passages and linked evidence.
          </p>
          <div className="sectionOverviewActions">
            <Link className="btn btnLarge sectionOverviewCta" to="/ai-sage">
              Open AI Sage
            </Link>
          </div>
        </article>

        <article className="card sectionOverviewCard sectionOverviewPrimaryCard">
          <p className="sectionOverviewEyebrow">Author Library</p>
          <h2 className="sectionOverviewTitle">Browse authors, documents, and curated passages.</h2>
          <p className="muted sectionOverviewDescription">
            Navigate the ingested writing corpus by author, collection, and document so you can read the source material directly.
          </p>
          <div className="sectionOverviewActions">
            <Link className="btn btnLarge sectionOverviewCta" to="/author-library">
              Open Author Library
            </Link>
          </div>
        </article>

        <article className="card sectionOverviewCard sectionOverviewPrimaryCard">
          <p className="sectionOverviewEyebrow">Author Ingestion</p>
          <h2 className="sectionOverviewTitle">Curate source discovery and ingestion for the library.</h2>
          <p className="muted sectionOverviewDescription">
            Add and validate author sources, fan out logical documents, and monitor ingestion jobs for your research corpus.
          </p>
          <div className="sectionOverviewActions">
            <Link className="btn btnLarge sectionOverviewCta" to="/author-ingestion">
              Ingest Author Writings
            </Link>
          </div>
        </article>

        <article className="card sectionOverviewCard">
          <p className="sectionOverviewEyebrow">Companies</p>
          <h2 className="sectionOverviewTitle">Keep company research accessible as a dedicated tab.</h2>
          <p className="muted sectionOverviewDescription">
            This will become the structured home for company dossiers, snapshots, and long-form research workflows.
          </p>
          <div className="sectionOverviewActions">
            <button className="btn btnLarge sectionOverviewCta" type="button" disabled>
              Companies Coming Soon
            </button>
          </div>
        </article>
      </section>
    </PageShell>
  );
}
