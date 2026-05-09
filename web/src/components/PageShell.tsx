import { useEffect, type ReactNode } from "react";
import { useShellHeader } from "../context/ShellHeaderContext";

type PageShellProps = {
  title: string;
  subtitle?: string;
  hideHeader?: boolean;
  headerActions?: ReactNode;
  className?: string;
  fillHeight?: boolean;
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
  hideHeader = false,
  headerActions,
  className,
  fillHeight = false,
  children,
}: PageShellProps) {
  const { hasProvider, setHeaderActions } = useShellHeader();

  useEffect(() => {
    if (!hasProvider) {
      return undefined;
    }
    setHeaderActions(headerActions ?? null);
    return () => {
      setHeaderActions(null);
    };
  }, [hasProvider, headerActions, setHeaderActions]);

  return (
    <div className={`pageShellWrap${fillHeight ? " pageShellWrapFillHeight" : ""}${className ? ` ${className}` : ""}`}>
      {!hideHeader ? (
        <header className="header dashboardHeader">
          <div className="titleBlock dashboardTitleBlock">
            <h1 className="title">{title}</h1>
            {subtitle ? <div className="subtitle">{subtitle}</div> : null}
          </div>
          {!hasProvider && headerActions ? <div className="dashboardHeaderActions">{headerActions}</div> : null}
        </header>
      ) : null}

      {children}
    </div>
  );
}
