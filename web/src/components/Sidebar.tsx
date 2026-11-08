import { Link, useLocation } from "react-router-dom";
import { APP_SECTIONS, UTILITY_NAV_ITEMS, findActiveSection, isNavItemActive } from "../lib/navigation";

export default function Sidebar() {
  const location = useLocation();
  const activeSection = findActiveSection(location.pathname);

  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="sidebarBrand">
        <Link aria-label="CapitalOS" className="sidebarBrandLink" to="/wealth">
          <span className="sidebarBrandWordmark">CapitalOS</span>
          <span className="sidebarBrandTag">Wealth operating system</span>
        </Link>
      </div>

      <nav className="sidebarNav">
        {APP_SECTIONS.map((section) => (
          <Link
            aria-label={section.label}
            key={section.id}
            className={`sidebarLink sidebarPrimaryLink${activeSection?.id === section.id ? " sidebarLinkActive" : ""}`}
            to={section.to}
          >
            <span className="sidebarPrimaryLabel">{section.label}</span>
          </Link>
        ))}
      </nav>

      {/* #317: Alerts is the header bell now; this area only shows if utilities return. */}
      {UTILITY_NAV_ITEMS.length > 0 && (
        <div className="sidebarUtilityArea">
          <div className="sidebarSectionLabel">Utilities</div>
          {UTILITY_NAV_ITEMS.map((item) => (
            <Link
              aria-label={item.label}
              key={item.to}
              className={`sidebarLink sidebarUtilityLink${isNavItemActive(item, location.pathname) ? " sidebarLinkActive" : ""}`}
              to={item.to}
            >
              <span>{item.label}</span>
            </Link>
          ))}
        </div>
      )}
    </aside>
  );
}
