export type DueTone = "overdue" | "warn" | "normal" | "not-synced";

export type DueStatus = {
  tone: DueTone;
  /** e.g. "Overdue", "Due in 3d", "Not synced" — no date suffix. */
  label: string;
  /** days until due, null when not synced */
  daysUntil: number | null;
};

/**
 * Mirrors the existing `current_due_source === "available_limit"` fallback in
 * CreditCards.tsx: when the issuer integration hasn't returned real statement
 * data, the due date is unreliable and must never be estimated — show "Not synced".
 */
export function computeDueStatus(
  params: { dueDate?: string | null; dueSource?: string | null },
  today: Date = new Date(),
): DueStatus {
  if (params.dueSource === "available_limit" || !params.dueDate) {
    return { tone: "not-synced", label: "Not synced", daysUntil: null };
  }

  const days = Math.round((new Date(params.dueDate).getTime() - today.getTime()) / 86_400_000);

  if (days < 0) {
    return { tone: "overdue", label: "Overdue", daysUntil: days };
  }
  if (days <= 7) {
    return { tone: "warn", label: `Due in ${days}d`, daysUntil: days };
  }
  return { tone: "normal", label: `Due in ${days}d`, daysUntil: days };
}

export function formatShortDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Sort key: unsynced rows sort last, then soonest due date first. */
export function dueSortValue(status: DueStatus, dueDate?: string | null): number {
  if (status.tone === "not-synced" || !dueDate) {
    return Number.POSITIVE_INFINITY;
  }
  return new Date(dueDate).getTime();
}
