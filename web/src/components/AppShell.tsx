import { Link, Outlet, useLocation } from "react-router-dom";
import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import InboxBell from "./InboxBell";
import RouteFallback from "./RouteFallback";
import RouteErrorBoundary from "./RouteErrorBoundary";
import { useAuth } from "../context/useAuth";
import { useTheme } from "../context/ThemeContext";
import { ShellHeaderProvider } from "../context/ShellHeaderContext";
import { findActiveSection, isNavItemActive } from "../lib/navigation";
import { NARROW_SHELL_QUERY, useMediaQuery } from "../lib/useMediaQuery";
import { watchActiveTab } from "../lib/tabRail";

export default function AppShell() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const activeSection = findActiveSection(location.pathname);
  const [headerActions, setHeaderActions] = useState<ReactNode>(null);
  // #239 (D-64): on a phone the top bar holds only the brand and the account menu. The
  // page's own controls (month pill, currency, CSV) go in a row under its title
  // (PageShell), and the theme switch moves into the account menu.
  const narrow = useMediaQuery(NARROW_SHELL_QUERY);
  // #264: the section tabs are one row that scrolls sideways when it doesn't fit (Wealth has 7);
  // the active tab is kept in view: on every route change, and again whenever the rail or the
  // tab changes size afterwards (fonts, a lazy page filling the top bar; #371).
  const tabsRef = useRef<HTMLElement | null>(null);
  const activeSectionLabel = activeSection?.label;
  useEffect(() => {
    const rail = tabsRef.current;
    return rail ? watchActiveTab(rail) : undefined;
  }, [location.pathname, activeSectionLabel]);

  return (
    <div className="appShell">
      {/* #151 / #131: keyboard users skip the sidebar and tabs straight to the page. */}
      <a className="skipLink" href="#main-content">
        Skip to content
      </a>
      <Sidebar />
      <main className="appShellMain">
        <ShellHeaderProvider setHeaderActions={setHeaderActions} actionsInPage={narrow}>
          {/* Always render the topbar — mobile brand + controls must show on every page */}
          <header className="appShellTopbar">
            {/* Mobile-only brand wordmark — hidden on desktop via CSS */}
            <Link className="appShellBrandMobile" to="/wealth" aria-label="CapitalOS home">
              CapitalOS
            </Link>

            {/* Tabs: only when there's a matching section */}
            {activeSection ? (
              <nav ref={tabsRef} className="appShellTabs" aria-label={`${activeSection.label} tabs`}>
                {activeSection.tabs
                  .filter((tab) => !tab.hidden)
                  .map((tab) => (
                    <Link
                      key={tab.to}
                      className={`appShellTab${isNavItemActive(tab, location.pathname) ? " appShellTabActive" : ""}`}
                      aria-current={isNavItemActive(tab, location.pathname) ? "page" : undefined}
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
              {headerActions && !narrow ? <div className="appShellTopbarActions">{headerActions}</div> : null}
              {narrow ? null : (
                <div className="coThemeToggle" role="group" aria-label="Theme">
                  <button
                    type="button"
                    className={`coThemeBtn${theme === "light" ? " coThemeBtnActive" : ""}`}
                    aria-pressed={theme === "light"}
                    onClick={() => setTheme("light")}
                  >
                    Light
                  </button>
                  <button
                    type="button"
                    className={`coThemeBtn${theme === "dark" ? " coThemeBtnActive" : ""}`}
                    aria-pressed={theme === "dark"}
                    onClick={() => setTheme("dark")}
                  >
                    Dark
                  </button>
                </div>
              )}
              {/* #317: the Data Hub inbox count, the same on every page and on a phone. */}
              <InboxBell narrow={narrow} />
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
                      {narrow ? (
                        <button
                          className="btn userMenuAction"
                          type="button"
                          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                        >
                          <span className="material-symbols-outlined userMenuActionIcon" aria-hidden="true">
                            {theme === "dark" ? "light_mode" : "dark_mode"}
                          </span>
                          <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
                        </button>
                      ) : null}
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

          {/* No pathname key (#148): it remounted Cash Flow on every tab switch, refetching
              everything and dropping local state. Different routes still mount fresh. */}
          <div id="main-content" className="appShellContent" tabIndex={-1}>
            {/* One page failing to render shows an error card here, not a blank app (#151);
                moving to another route clears it. */}
            <RouteErrorBoundary resetKey={location.pathname}>
              {/* Routes are lazy chunks (#145): keep the shell up while one loads. */}
              <Suspense fallback={<RouteFallback />}>
                <Outlet />
              </Suspense>
            </RouteErrorBoundary>
          </div>
        </ShellHeaderProvider>
      </main>
      {/* Mobile bottom navigation — hidden on desktop via CSS */}
      <nav className="coMobileBottomNav" aria-label="Mobile navigation">
        <Link
          className={`coMobileBottomNavItem${location.pathname.startsWith("/wealth") || location.pathname.startsWith("/holdings") || location.pathname.startsWith("/dividends") || location.pathname.startsWith("/income") || location.pathname.startsWith("/crypto") || location.pathname.startsWith("/cash") || location.pathname.startsWith("/risk") ? " coMobileBottomNavItemActive" : ""}`}
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
          {/* "Flow", not "Cash" (#239): Wealth → Cash is the balances page. */}
          <span className="coMobileBottomNavLabel">Flow</span>
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
