import "../App.css";
import PageShell from "../components/PageShell";
import { useTheme } from "../context/ThemeContext";

export default function Settings() {
  const { theme, toggleTheme } = useTheme();

  return (
    <PageShell title="Settings" subtitle="Application settings">
      <div className="wrap">
        <div className="card placeholderCard settingsCard">
          <div className="cardTitle">Appearance</div>
          <p className="muted">Theme controls live here now instead of the app shell.</p>
          <button className="btn settingsThemeToggle" type="button" onClick={toggleTheme}>
            {theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
          </button>
        </div>
      </div>
    </PageShell>
  );
}
