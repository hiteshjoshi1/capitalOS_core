import { Link } from "react-router-dom";
import "../App.css";
import "./Settings.css";
import "./AdminSettings.css";
import ChangePasswordCard from "../components/ChangePasswordCard";
import HomeRegionCard from "../components/HomeRegionCard";
import PageShell from "../components/PageShell";
import RiskThresholdsCard from "../components/RiskThresholdsCard";
import SettingsFactsCard from "../components/SettingsFactsCard";
import { useAuth } from "../context/useAuth";

export default function Settings() {
  const { user } = useAuth();

  return (
    <PageShell title="Settings" subtitle="Application settings">
      <div className="wrap settingsStack">
        {/* #399 (U23): the theme has one control, in the header (the user menu on a phone). */}
        <HomeRegionCard />
        <SettingsFactsCard />
        <RiskThresholdsCard />
        <ChangePasswordCard />
        {/* #321: shared-data tools (platforms, token allowlist, job status), admins only. */}
        {user?.is_admin ? (
          <div className="card settingsCard settingsAdminLink">
            <div>
              <div className="cardTitle">Admin</div>
              <p className="muted">Platform directory, token allowlist and background jobs.</p>
            </div>
            <Link className="btn" to="/settings/admin">
              Open admin
            </Link>
          </div>
        ) : null}
      </div>
    </PageShell>
  );
}
