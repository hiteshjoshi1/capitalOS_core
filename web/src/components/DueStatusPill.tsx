import type { DueStatus } from "../lib/dueStatus";

type DueStatusPillProps = {
  status: DueStatus;
  /** Optional short date suffix, e.g. "Jul 18", appended as "Due in 3d · Jul 18". */
  dateLabel?: string | null;
};

export default function DueStatusPill({ status, dateLabel }: DueStatusPillProps) {
  const text = dateLabel && status.tone !== "not-synced" ? `${status.label} · ${dateLabel}` : status.label;
  return <span className={`coDuePill coDuePill--${status.tone}`}>{text}</span>;
}
