import type { ReactNode } from "react";

/**
 * Wraps content that stays on screen while it refreshes (#148): the previous month's or
 * currency's numbers are dimmed (after a short delay, so a fast reply doesn't flash) and
 * marked `aria-busy`, and "Updating" is announced politely.
 */
export default function RefreshingRegion({
  busy,
  label = "Updating…",
  className,
  children,
}: {
  busy: boolean;
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`refreshingRegion${className ? ` ${className}` : ""}`}
      aria-busy={busy || undefined}
      data-refreshing={busy ? "true" : undefined}
    >
      <span className="srOnly" role="status" aria-live="polite">
        {busy ? label : ""}
      </span>
      {children}
    </div>
  );
}
