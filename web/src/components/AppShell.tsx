import { Link, Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import { useAuth } from "../context/useAuth";
import { findActiveSection, findActiveTab, isNavItemActive } from "../lib/navigation";

export default function AppShell() {
  const location = useLocation();
  const { user, logout } = useAuth();
  const activeSection = findActiveSection(location.pathname);
  const activeTab = activeSection ? findActiveTab(activeSection, location.pathname) : null;

  return (
    <div className="appShell">
      <Sidebar />
      <main className="appShellMain">
        {activeSection ? (
          <header className="appShellTopbar">
            <div className="appShellTopbarIntro">
              <h1 className="appShellSectionTitle">{activeSection.label}</h1>
            </div>

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
              <details className="userMenu">
                <summary className="userMenuSummary appShellUserPill">
                  <span className="appShellUserAvatarFrame" aria-hidden="true">
                    <span className="material-symbols-outlined appShellUserIcon">
                      person
                    </span>
                  </span>
                  <span className="appShellUserLabel">User</span>
                </summary>
                <div className="userMenuPanel">
                  <div className="userMenuSection">
                    <div className="cardTitle">Account</div>
                    <div className="userMenuAccountName">
                      {(user?.display_name || user?.username || "User").trim()}
                      {activeTab ? <span>{activeTab.label}</span> : null}
                    </div>
                    <div className="userMenuNavLinks">
                      <Link className="menuLink userMenuAction" to="/settings">Settings</Link>
                      <button
                        className="btn appShellLogoutButton userMenuAction"
                        type="button"
                        onClick={() => {
                          void logout();
                        }}
                      >
                        Log Out
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
      </main>
    </div>
  );
}
