import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { APP_SECTIONS, UTILITY_NAV_ITEMS, findActiveSection, isNavItemActive } from "../lib/navigation";

export default function Sidebar() {
  const location = useLocation();
  const [alertCount, setAlertCount] = useState<number>(0);
  const activeSection = findActiveSection(location.pathname);

  const hydrateAlertCount = useCallback(() => {
    api
      .alertNotifications()
      .then((response) => setAlertCount(response.total_count))
      .catch(() => {
        api.uploadReminderCount?.()
          ?.then((response) => setAlertCount(response.count))
          .catch(() => {});
      });
  }, []);

  useEffect(() => {
    hydrateAlertCount();
  }, [hydrateAlertCount]);

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
