import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";

export default function OperationsOverview() {
  return (
    <PageShell
      title="Operations Overview"
      subtitle="Run ingestion, connect accounts, and refresh market data from one operator surface."
    >
      <section className="grid sectionOverviewGrid">
        <article className="card sectionOverviewCard">
          <p className="sectionOverviewEyebrow">Overview</p>
          <h2 className="sectionOverviewTitle">Instrumentation first, workflows second.</h2>
          <p className="muted">
            Every operational action stays on its existing page while the shell groups them under a single section.
          </p>
        </article>

        <Link className="card sectionOverviewLinkCard" to="/ingest">
          <p className="sectionOverviewEyebrow">Ingest</p>
          <h2 className="sectionOverviewTitle">Upload statements and inspect import reports.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/accounts/new">
          <p className="sectionOverviewEyebrow">Add Accounts</p>
          <h2 className="sectionOverviewTitle">Create financial accounts with typed metadata.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/platforms">
          <p className="sectionOverviewEyebrow">Add Platforms</p>
          <h2 className="sectionOverviewTitle">Manage banks, brokers, exchanges, and wallet providers.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/crypto">
          <p className="sectionOverviewEyebrow">Add Crypto Wallets</p>
          <h2 className="sectionOverviewTitle">Connect chains and verify wallet ownership.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/market-data">
          <p className="sectionOverviewEyebrow">Refresh Market Data</p>
          <h2 className="sectionOverviewTitle">Refresh quotes and portfolio market snapshots.</h2>
        </Link>

        <Link className="card sectionOverviewLinkCard" to="/author-ingestion">
          <p className="sectionOverviewEyebrow">Author Ingestion</p>
          <h2 className="sectionOverviewTitle">Curate source discovery and ingestion for the library.</h2>
        </Link>
      </section>
    </PageShell>
  );
}
