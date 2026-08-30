import { Link, Outlet, useLocation } from "react-router-dom";
import { useState, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import { useAuth } from "../context/useAuth";
import { useTheme } from "../context/ThemeContext";
import { ShellHeaderProvider } from "../context/ShellHeaderContext";
import { findActiveSection, isNavItemActive } from "../lib/navigation";

export default function AppShell() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const activeSection = findActiveSection(location.pathname);
  const [headerActions, setHeaderActions] = useState<ReactNode>(null);

  return (
    <div className="appShell">
      <Sidebar />
      <main className="appShellMain">
        <ShellHeaderProvider setHeaderActions={setHeaderActions}>
          {/* Always render the topbar — mobile brand + controls must show on every page */}
          <header className="appShellTopbar">
            {/* Mobile-only brand wordmark — hidden on desktop via CSS */}
            <Link className="appShellBrandMobile" to="/wealth" aria-label="CapitalOS home">
              CapitalOS
            </Link>

            {/* Tabs: only when there's a matching section */}
            {activeSection ? (
              <nav className="appShellTabs" aria-label={`${activeSection.label} tabs`}>
                {activeSection.tabs
                  .filter((tab) => !tab.hidden)
                  .map((tab) => (
                    <Link
                      key={tab.to}
                      className={`appShellTab${isNavItemActive(tab, location.pathname) ? " appShellTabActive" : ""}`}
                      to={tab.to}
                    >
                      {tab.label}
                    </Link>
                  ))}
              </nav>
            ) : (
              /* Spacer so meta stays right-aligned on desktop when no tabs */
              <div className="appShellTabsSpacer" />
            )}

            <div className="appShellTopbarMeta">
              {headerActions ? <div className="appShellTopbarActions">{headerActions}</div> : null}
              <div className="coThemeToggle">
                <button
                  type="button"
                  className={`coThemeBtn${theme === "light" ? " coThemeBtnActive" : ""}`}
                  onClick={() => setTheme("light")}
                >
                  Light
                </button>
                <button
                  type="button"
                  className={`coThemeBtn${theme === "dark" ? " coThemeBtnActive" : ""}`}
                  onClick={() => setTheme("dark")}
                >
                  Dark
                </button>
              </div>
              <details className="userMenu">
                <summary className="userMenuSummary appShellUserPill">
                  <span className="appShellUserAvatarFrame" aria-hidden="true">
                    <span className="material-symbols-outlined appShellUserIcon">
                      person
                    </span>
                  </span>
                  <span className="appShellUserLabel">{(user?.display_name || user?.username || "User").trim()}</span>
                </summary>
                <div className="userMenuPanel">
                  <div className="userMenuSection">
                    <div className="userMenuNavLinks">
                      <Link className="menuLink userMenuAction" to="/settings">
                        <span className="material-symbols-outlined userMenuActionIcon" aria-hidden="true">settings</span>
                        <span>Settings</span>
                      </Link>
                      <button
                        className="btn appShellLogoutButton userMenuAction"
                        type="button"
                        onClick={() => {
                          void logout();
                        }}
                      >
                        <span className="material-symbols-outlined userMenuActionIcon" aria-hidden="true">logout</span>
                        <span>Log Out</span>
                      </button>
                    </div>
                  </div>
                </div>
              </details>
            </div>
          </header>

          <div key={location.pathname} className="appShellContent">
            <Outlet />
          </div>
        </ShellHeaderProvider>
      </main>
      {/* Mobile bottom navigation — hidden on desktop via CSS */}
      <nav className="coMobileBottomNav" aria-label="Mobile navigation">
        <Link
          className={`coMobileBottomNavItem${location.pathname.startsWith("/wealth") || location.pathname.startsWith("/holdings") || location.pathname.startsWith("/dividends") || location.pathname.startsWith("/crypto") || location.pathname.startsWith("/cash") || location.pathname.startsWith("/risk") ? " coMobileBottomNavItemActive" : ""}`}
          to="/wealth"
        >
          <span className="coMobileBottomNavDot" aria-hidden="true" />
          <span className="coMobileBottomNavLabel">Wealth</span>
        </Link>
        <Link
          className={`coMobileBottomNavItem${location.pathname.startsWith("/cash-flow") ? " coMobileBottomNavItemActive" : ""}`}
          to="/cash-flow"
        >
          <span className="coMobileBottomNavDot" aria-hidden="true" />
          <span className="coMobileBottomNavLabel">Cash</span>
        </Link>
        <Link
          className={`coMobileBottomNavItem${location.pathname.startsWith("/liabilities") ? " coMobileBottomNavItemActive" : ""}`}
          to="/liabilities"
        >
          <span className="coMobileBottomNavDot" aria-hidden="true" />
          <span className="coMobileBottomNavLabel">Liabilities</span>
        </Link>
        <Link
          className={`coMobileBottomNavItem${location.pathname.startsWith("/operations") ? " coMobileBottomNavItemActive" : ""}`}
          to="/operations"
        >
          <span className="coMobileBottomNavDot" aria-hidden="true" />
          <span className="coMobileBottomNavLabel">More</span>
        </Link>
      </nav>
    </div>
  );
}
