import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import { api } from "../lib/api";

type NavChild = { label: string; to: string };
type NavSection = { label: string; children: NavChild[] };

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Wealth",
    children: [
      { label: "Overview", to: "/wealth" },
      { label: "Stocks", to: "/holdings" },
      { label: "Crypto", to: "/crypto/holdings" },
      { label: "Cash", to: "/cash" },
    ],
  },
  {
    label: "Liabilities",
    children: [
      { label: "Credit Cards", to: "/credit-cards" },
      { label: "Loans", to: "/loans" },
    ],
  },
  {
    label: "Intelligence",
    children: [
      { label: "Companies", to: "/companies" },
      { label: "Alerts", to: "/alerts" },
      { label: "AI Guru", to: "/ai-guru" },
    ],
  },
  {
    label: "Operations",
    children: [
      { label: "Ingest", to: "/ingest" },
      { label: "Market Data", to: "/market-data" },
      { label: "Cash Mapping", to: "/cash-flow/mapping" },
    ],
  },
];

function isSectionOpen(section: NavSection, pathname: string): boolean {
  return section.children.some(
    (child) => pathname === child.to || pathname.startsWith(child.to + "/"),
  );
}

export default function Sidebar() {
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(
    () => {
      const initial: Record<string, boolean> = {};
      NAV_SECTIONS.forEach((section) => {
        initial[section.label] = isSectionOpen(section, location.pathname);
      });
      return initial;
    },
  );
  const [alertCount, setAlertCount] = useState<number>(0);

  useEffect(() => {
    api.uploadReminderCount?.()
      ?.then((r) => setAlertCount(r.count))
      .catch(() => {});
  }, []);

  const toggleSection = (label: string) => {
    setOpenSections((prev) => ({ ...prev, [label]: !prev[label] }));
  };

  const isActive = (to: string) => location.pathname === to;

  return (
    <aside className="sidebar" aria-label="Main navigation">
      <nav className="sidebarNav">
        <Link
          className={`sidebarLink sidebarTopLink${location.pathname === "/" ? " sidebarLinkActive" : ""}`}
          to="/"
        >
          Dashboard
        </Link>

        {NAV_SECTIONS.map((section) => (
          <div key={section.label} className="sidebarSection">
            <button
              className="sidebarSectionToggle"
              type="button"
              onClick={() => toggleSection(section.label)}
              aria-expanded={!!openSections[section.label]}
            >
              <span>{section.label}</span>
              <span className="sidebarChevron" aria-hidden="true">
                {openSections[section.label] ? "▾" : "▸"}
              </span>
            </button>
            {openSections[section.label] && (
              <div className="sidebarChildren">
                {section.children.map((child) => (
                  <Link
                    key={child.to}
                    className={`sidebarLink sidebarChildLink${isActive(child.to) ? " sidebarLinkActive" : ""}`}
                    to={child.to}
                  >
                    <span>{child.label}</span>
                    {child.to === "/alerts" && alertCount > 0 && (
                      <span
                        className="sidebarBadge alertBadge"
                        aria-label={`${alertCount} upload alerts`}
                      >
                        {alertCount}
                      </span>
                    )}
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))}

        <Link
          className={`sidebarLink sidebarTopLink${location.pathname === "/settings" ? " sidebarLinkActive" : ""}`}
          to="/settings"
        >
          Settings
        </Link>
      </nav>

      <div className="sidebarUserArea">
        <div className="sidebarUserInfo">
          <span className="sidebarAvatar" aria-hidden="true">
            U
          </span>
          <span className="sidebarUserName">User</span>
        </div>
        <button
          className="btn sidebarThemeToggle"
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle theme"
        >
          {theme === "dark" ? "🌙 Dark" : "☀️ Light"}
        </button>
      </div>
    </aside>
  );
}
