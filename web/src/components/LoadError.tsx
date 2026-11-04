import type { ReactNode } from "react";

/**
 * The one "couldn't load" state (#151, review #130 finding 7.5). It is announced
 * (`role="alert"`), says what failed, and offers a retry, so a failed panel never looks
 * like a zero or an empty list.
 */
export default function LoadError({
  title = "Couldn't load this",
  error,
  onRetry,
  compact = false,
  children,
}: {
  title?: string;
  error?: Error | string | null;
  onRetry?: () => void;
  /** Inline variant for a panel inside a card (no card chrome of its own). */
  compact?: boolean;
  children?: ReactNode;
}) {
  const message = typeof error === "string" ? error : error?.message;
  return (
    <div className={compact ? "loadError loadErrorCompact" : "card error loadError"} role="alert">
      <div className="cardTitle loadErrorTitle">{title}</div>
      {message ? <p className="loadErrorMessage">{message}</p> : null}
      {children}
      {onRetry ? (
        <button type="button" className="btn loadErrorRetry" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
