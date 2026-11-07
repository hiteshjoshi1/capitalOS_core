import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useApiResource } from "../lib/useApiResource";
import "../App.css";
import PageShell from "../components/PageShell";
import { formatPlatformLabel } from "../lib/platformLabels";

export default function Alerts() {
  // #148: the same resource as the sidebar's alert badge, so opening Alerts shares one
  // request instead of fetching /alerts/notifications twice.
  const notifications = useApiResource("alertNotifications", () => api.alertNotifications());
  const reminders = notifications.data?.upload_reminders ?? [];
  const state = notifications.error ? "error" : notifications.data ? "ready" : "loading";
  const err = notifications.error?.message ?? "";

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
          <div className="card alertEmptyState" role="status" aria-label="No alerts">
            <p className="alertEmptyIcon" aria-hidden="true">✅</p>
            <p className="alertEmptyText">All accounts are up to date. No upload reminders.</p>
          </div>
        )}

        {state === "ready" && reminders.length > 0 && (
          <>
            <h2 className="alertSectionTitle">Upload Reminders</h2>
            <div className="alertList" role="group" aria-label="Upload reminders">
              {reminders.map((r) => (
                <div key={r.account_id} className="card alertCard" role="group" aria-label={`Alert for ${r.account_name}`}>
                  <div className="alertCardHeader">
                    <span className="alertIcon" aria-hidden="true">⚠️</span>
                    <span className="alertAccountName">{r.account_name}</span>
                    <span className="pill alertPlatformBadge">{formatPlatformLabel(r.platform)}</span>
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
