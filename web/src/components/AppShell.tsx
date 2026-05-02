import { Link, Outlet, useLocation } from "react-router-dom";
import { useState, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import { useAuth } from "../context/useAuth";
import { ShellHeaderProvider } from "../context/ShellHeaderContext";
import { findActiveSection, isNavItemActive } from "../lib/navigation";

export default function AppShell() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const activeSection = findActiveSection(location.pathname);
  const [headerActions, setHeaderActions] = useState<ReactNode>(null);

  return (
    <div className="appShell">
      <Sidebar />
      <main className="appShellMain">
        <ShellHeaderProvider setHeaderActions={setHeaderActions}>
          {activeSection ? (
            <header className="appShellTopbar">
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

              <div className="appShellTopbarMeta">
                {headerActions ? <div className="appShellTopbarActions">{headerActions}</div> : null}
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
          ) : null}

          <div className="appShellContent">
            <Outlet />
          </div>
        </ShellHeaderProvider>
      </main>
    </div>
  );
}
