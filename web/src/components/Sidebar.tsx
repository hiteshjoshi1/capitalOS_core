import { Link, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import { APP_SECTIONS, UTILITY_NAV_ITEMS, findActiveSection, isNavItemActive } from "../lib/navigation";

export default function Sidebar() {
  const location = useLocation();
  const activeSection = findActiveSection(location.pathname);
  // #149: the badge needs only the count, not the whole notifications list.
  const notificationsCount = useApiResource("alertNotificationsCount", () => api.alertNotificationsCount());
  const alertCount = notificationsCount.data?.total_count ?? 0;

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
            {item.badgeKey === "alerts" && alertCount > 0 ? (
              <span className="sidebarBadge alertBadge" aria-label={`${alertCount} alerts`}>
                {alertCount}
              </span>
            ) : null}
          </Link>
        ))}
      </div>
    </aside>
  );
}
