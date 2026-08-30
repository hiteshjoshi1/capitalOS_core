import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { UploadReminder } from "../lib/api";
import "../App.css";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function Alerts() {
  const [state, setState] = useState<LoadState>("loading");
  const [err, setErr] = useState<string>("");
  const [reminders, setReminders] = useState<UploadReminder[]>([]);

  // Initial hydration from backend
  useEffect(() => {
    void (async () => {
      try {
        setErr("");
        const data = await api.alertNotifications();
        setReminders(data.upload_reminders);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, []);

  const totalCount = reminders.length;

  return (
    <PageShell
      title="Alerts"
      subtitle="Upload reminders."
      activeRoute="/alerts"
    >
      <main>
        {state === "loading" && (
          <p className="muted" aria-busy="true">
            Loading alerts…
          </p>
        )}

        {state === "error" && (
          <p className="bad" role="alert">
            Failed to load alerts: {err}
          </p>
        )}

        {state === "ready" && totalCount === 0 && (
          <div className="card alertEmptyState" aria-label="No alerts">
            <p className="alertEmptyIcon" aria-hidden="true">✅</p>
            <p className="alertEmptyText">All accounts are up to date. No upload reminders.</p>
          </div>
        )}

        {state === "ready" && reminders.length > 0 && (
          <>
            <h2 className="alertSectionTitle">Upload Reminders</h2>
            <div className="alertList" aria-label="Upload reminders">
              {reminders.map((r) => (
                <div key={r.account_id} className="card alertCard" aria-label={`Alert for ${r.account_name}`}>
                  <div className="alertCardHeader">
                    <span className="alertIcon" aria-hidden="true">⚠️</span>
                    <span className="alertAccountName">{r.account_name}</span>
                    <span className="pill alertPlatformBadge">{r.platform}</span>
                    <span className="muted alertAccountType">{r.account_type}</span>
                  </div>

                  <p className="alertMessage">{r.message}</p>

                  <div className="alertDates">
                    <span>
                      Last upload:{" "}
                      <strong>{r.last_upload_date ?? "—"}</strong>
                    </span>
                    <span>
                      Last transaction:{" "}
                      <strong>{r.last_transaction_date ?? "—"}</strong>
                    </span>
                    <span className="bad">
                      <strong>{r.days_since_upload} days</strong> overdue
                    </span>
                  </div>

                  <div className="alertActions">
                    <Link className="btn" to={`/ingest?account_id=${encodeURIComponent(String(r.account_id))}`}>
                      Go to Ingest →
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </main>
    </PageShell>
  );
}
