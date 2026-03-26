import { type ReactNode } from "react";

type PageShellProps = {
  title: string;
  subtitle?: string;
  headerActions?: ReactNode;
  /** @deprecated Navigation moved to Sidebar; kept for backward compatibility */
  activeRoute?: string;
  /** @deprecated Navigation moved to Sidebar; kept for backward compatibility */
  secondaryNavItem?: unknown;
  /** @deprecated Badge counts shown in Sidebar; kept for backward compatibility */
  unmappedCount?: number;
  /** @deprecated Settings moved to Sidebar; kept for backward compatibility */
  userMenuSettings?: ReactNode;
  /** @deprecated Menu moved to Sidebar; kept for backward compatibility */
  onUserMenuOpen?: () => void;
  children: ReactNode;
};

export default function PageShell({
  title,
  subtitle,
  headerActions,
  children,
}: PageShellProps) {
  return (
    <div className="wrap">
      <header className="header dashboardHeader">
        <div className="titleBlock dashboardTitleBlock">
          <h1 className="title">{title}</h1>
          {subtitle ? <div className="subtitle">{subtitle}</div> : null}
        </div>
        {headerActions ? (
          <div className="dashboardNavArea">
            <div className="pageHeaderActions">{headerActions}</div>
          </div>
        ) : null}
      </header>

      {children}
    </div>
  );
}

