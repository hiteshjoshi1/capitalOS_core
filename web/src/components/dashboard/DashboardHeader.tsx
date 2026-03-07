import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

type Theme = "dark" | "light";

type DashboardHeaderProps = {
  health: string;
  asOf: string | null;
  month: string;
  baseCurrency: string;
  theme: Theme;
  onMonthChange: (month: string) => void;
  onBaseCurrencyChange: (baseCurrency: string) => void;
  onToggleTheme: () => void;
};

const BASE_CURRENCY_OPTIONS = ["SGD", "USD", "HKD", "INR"] as const;

export default function DashboardHeader({
  health,
  asOf,
  month,
  baseCurrency,
  theme,
  onMonthChange,
  onBaseCurrencyChange,
  onToggleTheme,
}: DashboardHeaderProps) {
  const menuRef = useRef<HTMLDetailsElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      const menu = menuRef.current;
      if (!menu || !menu.open) {
        return;
      }
      const target = event.target as Node | null;
      if (target && !menu.contains(target)) {
        menu.open = false;
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      const menu = menuRef.current;
      if (menu?.open) {
        menu.open = false;
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  return (
    <header className="header dashboardHeader">
      <div className="titleBlock dashboardTitleBlock">
        <h1 className="title">CapitalOS Dashboard</h1>
        <div className="headerMeta">
          <span className="pill">API: {health}</span>
          <span className="pill">As of: {asOf ?? "—"}</span>
        </div>
      </div>

      <div className="dashboardNavArea">
        <nav className="pillRow topNavLinks" aria-label="Primary navigation">
          <Link className="pill topNavLink" to="/">
            Dashboard
          </Link>
          <Link className="pill topNavLink" to="/ingest">
            Ingest
          </Link>
        </nav>

        <details className="userMenu" ref={menuRef}>
          <summary className="pill userMenuSummary" aria-label="User menu">
            <span className="avatar" aria-hidden="true">
              U
            </span>
            <span>User</span>
          </summary>
          <div className="userMenuPanel">
            <div className="cardTitle">Settings</div>
            <label className="field">
              <span className="label">Base Currency</span>
              <select
                className="input"
                aria-label="Base currency"
                value={baseCurrency}
                onChange={(event) => onBaseCurrencyChange(event.target.value)}
              >
                {BASE_CURRENCY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="label">Month</span>
              <input
                className="input"
                aria-label="Month"
                type="month"
                value={month}
                onChange={(event) => onMonthChange(event.target.value)}
              />
            </label>
            <button className="btn" type="button" onClick={onToggleTheme}>
              Theme: {theme === "dark" ? "Dark" : "Light"}
            </button>
            <button className="btn" type="button" disabled>
              Sign in (coming soon)
            </button>
          </div>
        </details>
      </div>
    </header>
  );
}
