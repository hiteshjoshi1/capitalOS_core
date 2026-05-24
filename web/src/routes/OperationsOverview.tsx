import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";

type DataHubAction = {
  label: string;
  title: string;
  description: string;
  to: string;
  cta: string;
  primary?: boolean;
};

const DATA_HUB_ACTIONS: DataHubAction[] = [
  {
    label: "Import Statements",
    title: "Upload statements and inspect import reports.",
    description: "Bring in new broker, bank, and card statements, then verify what CapitalOS parsed before it lands in the ledger.",
    to: "/ingest",
    cta: "Import Statements",
    primary: true,
  },
  {
    label: "Refresh Market Data",
    title: "Refresh quotes and portfolio market snapshots.",
    description: "Pull the latest market data so valuations, positions, and downstream research surfaces stay current.",
    to: "/market-data",
    cta: "Refresh Stock Quotes",
  },
  {
    label: "Add Crypto Wallets",
    title: "Connect chains and verify wallet ownership.",
    description: "Attach wallet addresses, verify control, and expand on-chain balances and token exposure coverage.",
    to: "/crypto",
    cta: "Add Crypto Wallet",
  },
  {
    label: "Add Accounts",
    title: "Create financial accounts with typed metadata.",
    description: "Set up banks, brokers, cards, and internal ledgers so new statements have the right destination.",
    to: "/accounts/new",
    cta: "Add Accounts",
  },
  {
    label: "Add Platforms",
    title: "Manage banks, brokers, exchanges, and wallet providers.",
    description: "Maintain the platform directory that powers imports, holdings attribution, and account metadata.",
    to: "/platforms",
    cta: "Add a Platform",
  },
];

export default function OperationsOverview() {
  return (
    <PageShell
      title="Data Hub"
      subtitle="Import statements, manage source connections, and run the operational workflows that feed the system."
    >
      <section className="grid sectionOverviewGrid">
        {DATA_HUB_ACTIONS.map((action) => (
          <article
            key={action.to}
            className={`card sectionOverviewCard${action.primary ? " sectionOverviewPrimaryCard" : ""}`}
          >
            <p className="sectionOverviewEyebrow">{action.label}</p>
            <h2 className="sectionOverviewTitle">{action.title}</h2>
            <p className="muted sectionOverviewDescription">{action.description}</p>
            <div className="sectionOverviewActions">
              <Link className="btn btnLarge sectionOverviewCta" to={action.to}>
                {action.cta}
              </Link>
            </div>
          </article>
        ))}
      </section>
    </PageShell>
  );
}
