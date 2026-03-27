import "../App.css";
import PageShell from "../components/PageShell";

export default function Settings() {
  return (
    <PageShell title="Settings" subtitle="Application settings">
      <div className="wrap">
        <div className="card placeholderCard">
          <div className="cardTitle">Settings</div>
          <p className="muted">Application settings will appear here in a future release.</p>
        </div>
      </div>
    </PageShell>
  );
}
