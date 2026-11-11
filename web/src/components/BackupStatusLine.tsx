import { api } from "../lib/api";
import { backupLine } from "../lib/backupStatus";
import { useApiResource } from "../lib/useApiResource";

/**
 * Data Hub → Backups (#399, U22, D-111): when the newest verified backup was made, the next daily
 * run and where the backups live. Amber after 2 days, red after 7 or a failed run (the Inbox
 * says the same). Nothing shows where no backup reports (worktrees, the test instance).
 */
export default function BackupStatusLine() {
  const status = useApiResource("backupStatus", () => api.backupStatus());
  const line = backupLine(status.data);
  if (!line) return null;
  return (
    <section className={`card inboxDetails backupLine backupLine-${line.tone}`} aria-label="Backups" role="status">
      <div className="backupLineText">
        <span className="material-symbols-outlined backupLineIcon" aria-hidden="true">
          {line.tone === "ok" ? "cloud_done" : "cloud_off"}
        </span>
        <span>{line.text}</span>
      </div>
      {line.detail ? <div className="muted backupLineDetail">{line.detail}</div> : null}
    </section>
  );
}
