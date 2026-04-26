import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../context/useAuth";
import { api } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";

type NavChild = { label: string; to: string };
type NavSection = { label: string; children: NavChild[] };

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Wealth",
    children: [
      { label: "Overview", to: "/wealth" },
      { label: "Stocks", to: "/holdings" },
      { label: "Dividends", to: "/dividends" },
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
      { label: "AI Sage", to: "/ai-sage" },
      { label: "Author Library", to: "/author-library" },
    ],
  },
  {
    label: "Operations",
    children: [
      { label: "Accounts", to: "/accounts/new" },
      { label: "Platforms", to: "/platforms" },
      { label: "Crypto Wallets", to: "/crypto" },
      { label: "Ingest", to: "/ingest" },
      { label: "Market Data", to: "/market-data" },
      { label: "Author Sources", to: "/author-ingestion" },
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
  const { user, logout } = useAuth();
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(
    () =>
      Object.fromEntries(
        NAV_SECTIONS.map((s) => [
          s.label,
          isSectionOpen(s, location.pathname),
        ]),
      ),
  );
  const [alertCount, setAlertCount] = useState<number>(0);

  const hydrateAlertCount = useCallback(() => {
    api
      .alertNotifications()
      .then((r) => setAlertCount(r.total_count))
      .catch(() => {
        // Fallback to upload-reminder count if the unified endpoint is unavailable
        api.uploadReminderCount?.()
          ?.then((r) => setAlertCount(r.count))
          .catch(() => {});
      });
  }, []);

  // Initial hydration: fetch total count from unified notifications endpoint
  useEffect(() => {
    hydrateAlertCount();
  }, [hydrateAlertCount]);

  // Stay fresh via shared realtime websocket — no polling
  useEffect(() => {
    const unsubscribe = subscribeToRealtimeTopic("author-ingestion", {
      onEvent: () => {
        hydrateAlertCount();
      },
      onStatusChange: (status) => {
        if (status === "connected") {
          hydrateAlertCount();
        }
      },
    });
    return () => {
      unsubscribe();
    };
  }, [hydrateAlertCount]);

  const toggleSection = (label: string) => {
    setOpenSections((prev) => ({ ...prev, [label]: !prev[label] }));
  };

  const isActive = (to: string) =>
    location.pathname === to || location.pathname.startsWith(to + "/");

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
                        aria-label={`${alertCount} alerts`}
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

      <div className="sidebarUserArea" aria-label="User menu">
        <div className="sidebarUserInfo">
          <span className="sidebarAvatar" aria-hidden="true">
            {(user?.username || "U").slice(0, 1).toUpperCase()}
          </span>
          <span className="sidebarUserName">{user?.display_name || user?.username || "User"}</span>
        </div>
        <button
          className="btn sidebarThemeToggle"
          type="button"
          aria-label="Toggle theme"
          onClick={toggleTheme}
        >
          {theme === "dark" ? "Theme: Dark" : "Theme: Light"}
        </button>
        <button
          className="btn sidebarThemeToggle"
          type="button"
          onClick={() => {
            void logout();
          }}
        >
          Log Out
        </button>
      </div>
    </aside>
  );
}
