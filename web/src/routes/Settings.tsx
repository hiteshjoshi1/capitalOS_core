import { Link } from "react-router-dom";
import "../App.css";
import "./AdminSettings.css";
import ChangePasswordCard from "../components/ChangePasswordCard";
import HomeRegionCard from "../components/HomeRegionCard";
import PageShell from "../components/PageShell";
import RiskThresholdsCard from "../components/RiskThresholdsCard";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../context/useAuth";

export default function Settings() {
  const { theme, toggleTheme } = useTheme();
  const { user } = useAuth();

  return (
    <PageShell title="Settings" subtitle="Application settings">
      <div className="wrap settingsStack">
        <div className="card placeholderCard settingsCard">
          <div className="cardTitle">Appearance</div>
          <p className="muted">Theme controls live here now instead of the app shell.</p>
          <button className="btn settingsThemeToggle" type="button" onClick={toggleTheme}>
            {theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
          </button>
        </div>
        <HomeRegionCard />
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
