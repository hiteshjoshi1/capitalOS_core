// Data Hub's backup line (#399, U22): "Last verified backup 13:00 today · next 13:00 tomorrow · iCloud Drive".
import type { BackupStatus } from "./api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "13:00 today", "13:00 yesterday", "13:00 tomorrow", else "13:00 on 9 Nov" (this device's time). */
export function relativeDayTime(iso: string | null, now: Date = new Date()): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay(d, now)) return `${hm} today`;
  if (sameDay(d, yesterday)) return `${hm} yesterday`;
  if (sameDay(d, tomorrow)) return `${hm} tomorrow`;
  const month = MONTHS[d.getMonth()];
  return `${hm} on ${d.getDate()} ${month}${d.getFullYear() === now.getFullYear() ? "" : ` ${d.getFullYear()}`}`;
}

export type BackupLine = { tone: "ok" | "warn" | "bad"; text: string; detail: string | null };

/** The one line Data Hub shows, or null when no backup reports here (a worktree, the test instance). */
export function backupLine(status: BackupStatus | null | undefined, now: Date = new Date()): BackupLine | null {
  if (!status || !status.available) return null;
  const parts: string[] = [];
  const last = relativeDayTime(status.last_verified_at, now);
  parts.push(last ? `Last verified backup ${last}` : "No verified backup yet");
  const next = relativeDayTime(status.next_run_at, now);
  if (next) parts.push(`next ${next}`);
  if (status.location_label) parts.push(status.location_label);
  const kept: string[] = [];
  if (status.sets != null) kept.push(`${status.sets} kept`);
  if (status.encrypted === true) kept.push("encrypted");
  if (status.encrypted === false) kept.push("not encrypted");
  let detail: string | null = kept.length ? kept.join(", ") : null;
  if (status.last_run_ok === false) {
    const when = relativeDayTime(status.last_run_at, now);
    detail = `The last daily run${when ? ` (${when})` : ""} failed. On the Mac: make backup-status.`;
  } else if (status.stale) {
    detail = "Older than 2 days. On the Mac: make backup-now (a sleeping Mac runs it when it wakes).";
  }
  return { tone: status.very_stale ? "bad" : status.stale ? "warn" : "ok", text: parts.join(" · "), detail };
}
