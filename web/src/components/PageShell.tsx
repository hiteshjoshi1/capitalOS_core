import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";

type NavItem = {
  label: string;
  to: string;
};

type PageShellProps = {
  title: string;
  subtitle?: string;
  headerActions?: ReactNode;
  activeRoute: string;
  secondaryNavItem?: NavItem;
  userMenuSettings?: ReactNode;
  children: ReactNode;
};

const MENU_NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", to: "/" },
  { label: "Holdings", to: "/holdings" },
  { label: "Cash", to: "/cash" },
  { label: "Credit Cards", to: "/credit-cards" },
  { label: "Crypto Wallets", to: "/crypto" },
  { label: "Crypto Holdings", to: "/crypto/holdings" },
  { label: "Ingest", to: "/ingest" },
  { label: "Market Data", to: "/market-data" },
];

function isActiveRoute(activeRoute: string, navPath: string) {
  return activeRoute === navPath;
}

function getPrimaryNavItems(activeRoute: string, secondaryNavItem?: NavItem): NavItem[] {
  if (activeRoute === "/") {
    return [{ label: "Ingest", to: "/ingest" }];
  }

  if (secondaryNavItem) {
    return [
      { label: "Dashboard", to: "/" },
      secondaryNavItem,
    ];
  }

  return [{ label: "Dashboard", to: "/" }];
}

function isPrimaryNavItemActive(activeRoute: string, navPath: string, secondaryNavItem?: NavItem) {
  if (isActiveRoute(activeRoute, navPath)) {
    return true;
  }
  return !!secondaryNavItem && navPath === secondaryNavItem.to;
}

export default function PageShell({
  title,
  subtitle,
  headerActions,
  activeRoute,
  secondaryNavItem,
  userMenuSettings,
  children,
}: PageShellProps) {
  const menuRef = useRef<HTMLDetailsElement | null>(null);
  const { theme, toggleTheme } = useTheme();
  const primaryNavItems = getPrimaryNavItems(activeRoute, secondaryNavItem);

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

  const closeUserMenu = () => {
    const menu = menuRef.current;
    if (menu?.open) {
      menu.open = false;
    }
  };

  return (
    <div className="wrap">
      <header className="header dashboardHeader">
        <div className="titleBlock dashboardTitleBlock">
          <h1 className="title">{title}</h1>
          {subtitle ? <div className="subtitle">{subtitle}</div> : null}
        </div>

        <div className="dashboardNavArea">
          {headerActions ? <div className="pageHeaderActions">{headerActions}</div> : null}

          <nav className="pillRow topNavLinks" aria-label="Primary navigation">
            {primaryNavItems.map((item) => (
              <Link
                key={item.to}
                className={`pill topNavLink${isPrimaryNavItemActive(activeRoute, item.to, secondaryNavItem) ? " topNavLinkActive" : ""}`}
                to={item.to}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <details className="userMenu" ref={menuRef}>
            <summary className="pill userMenuSummary" aria-label="User menu">
              <span className="avatar" aria-hidden="true">
                U
              </span>
              <span>User</span>
            </summary>
            <div className="userMenuPanel">
              <section className="userMenuSection" aria-label="Manage">
                <div className="cardTitle">Manage</div>
                <Link className="menuLink menuLinkPrimary" to="/accounts/new" onClick={closeUserMenu}>
                  <span aria-hidden="true">+</span>
                  <span>Add Account</span>
                </Link>
              </section>

              {userMenuSettings ? (
                <section className="userMenuSection" aria-label="Settings">
                  <div className="cardTitle">Settings</div>
                  {userMenuSettings}
                </section>
              ) : null}

              <section className="userMenuSection" aria-label="Navigate">
                <div className="cardTitle">Navigate</div>
                <div className="userMenuNavLinks">
                  {MENU_NAV_ITEMS.map((item) => (
                    <Link key={`menu-${item.to}`} className="menuLink" to={item.to} onClick={closeUserMenu}>
                      {item.label}
                    </Link>
                  ))}
                </div>
              </section>

              <section className="userMenuSection" aria-label="Appearance">
                <div className="cardTitle">Appearance</div>
                <button className="btn" type="button" onClick={toggleTheme}>
                  Theme: {theme === "dark" ? "Dark" : "Light"}
                </button>
              </section>
            </div>
          </details>
        </div>
      </header>

      {children}
    </div>
  );
}
