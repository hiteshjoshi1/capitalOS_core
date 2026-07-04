import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import type { SystemNotification, UploadReminder, RagAuthorIngestionEventPayload, RealtimeEventEnvelope } from "../lib/api";
import "../App.css";
import PageShell from "../components/PageShell";

type LoadState = "idle" | "loading" | "ready" | "error";

function formatDatetime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function realtimeEventToSystemNotification(
  event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>,
): SystemNotification {
  return {
    id: event.id,
    alert_type: "system_notification",
    topic: event.topic,
    event_name: event.event_name,
    author_id: event.author_id ?? null,
    source_id: event.source_id ?? null,
    job_id: event.job_id ?? null,
    batch_id: event.batch_id ?? null,
    status: event.status ?? null,
    message: (() => {
      const payload = event.payload;
      const authorName = payload.author?.name ?? event.author_id ?? "Unknown author";
      const source = payload.source;
      const job = payload.job;
      const batch = payload.batch;
      switch (event.event_name) {
        case "batch_submitted":
          return `Ingestion batch started for ${authorName}: ${batch?.source_count ?? "?"} sources queued.`;
        case "source_queued":
          return `Source queued for ingestion for ${authorName}: ${source?.url ?? "source"}`;
        case "source_running":
          return `Ingestion in progress for ${authorName}: ${source?.url ?? "source"}`;
        case "source_ingested":
          return `Successfully ingested source for ${authorName}: ${source?.url ?? "source"}`;
        case "source_failed": {
          const reason = (payload as Record<string, unknown>).failure_reason ?? job?.error ?? "unknown error";
          return `Ingestion failed for ${authorName}: ${source?.url ?? "source"}. Reason: ${String(reason)}`;
        }
        case "batch_completed": {
          const completed = batch?.completed_source_count ?? "?";
          const failed = batch?.failed_source_count ?? 0;
          const total = batch?.source_count ?? "?";
          return failed
            ? `Ingestion batch completed for ${authorName}: ${completed}/${total} sources ingested, ${failed} failed.`
            : `Ingestion batch completed for ${authorName}: ${completed}/${total} sources ingested.`;
        }
        default:
          return `Author ingestion event: ${event.event_name} for ${authorName} (status: ${event.status ?? "?"})`;
      }
    })(),
    created_at: event.created_at ?? new Date().toISOString(),
    payload: event.payload as Record<string, unknown>,
  };
}

export default function Alerts() {
  const [state, setState] = useState<LoadState>("loading");
  const [err, setErr] = useState<string>("");
  const [reminders, setReminders] = useState<UploadReminder[]>([]);
  const [systemNotifications, setSystemNotifications] = useState<SystemNotification[]>([]);

  const hydrateAlerts = useCallback(async (opts?: { markLoading?: boolean }) => {
    try {
      if (opts?.markLoading) {
        setState("loading");
      }
      setErr("");
      const data = await api.alertNotifications();
      setReminders(data.upload_reminders);
      setSystemNotifications(data.system_notifications);
      setState("ready");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }, []);

  // Initial hydration from backend
  useEffect(() => {
    void (async () => {
      try {
        setErr("");
        const data = await api.alertNotifications();
        setReminders(data.upload_reminders);
        setSystemNotifications(data.system_notifications);
        setState("ready");
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      }
    })();
  }, []);

  // Stay fresh via shared realtime websocket — no polling
  useEffect(() => {
    const unsubscribe = subscribeToRealtimeTopic<RagAuthorIngestionEventPayload>("author-ingestion", {
      onEvent: (event) => {
        const notification = realtimeEventToSystemNotification(event);
        setSystemNotifications((prev) => [notification, ...prev]);
      },
      onStatusChange: (status) => {
        if (status === "connected") {
          void hydrateAlerts({ markLoading: true });
        }
      },
    });
    return () => {
      unsubscribe();
    };
  }, [hydrateAlerts]);

  const totalCount = reminders.length + systemNotifications.length;

  return (
    <PageShell
      title="Alerts"
      subtitle="Upload reminders and system notifications."
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

        {state === "ready" && systemNotifications.length > 0 && (
          <>
            <h2 className="alertSectionTitle">System Notifications</h2>
            <div className="alertList" aria-label="System notifications">
              {systemNotifications.map((n) => (
                <div key={n.id} className="card alertCard systemNotificationCard" aria-label={`Notification: ${n.event_name}`}>
                  <div className="alertCardHeader">
                    <span className="alertIcon" aria-hidden="true">
                      {n.status === "failed" ? "❌" : n.status === "done" || n.status === "ingested" ? "✅" : "🔔"}
                    </span>
                    <span className="alertAccountName">{n.author_id ?? "System"}</span>
                    <span className="pill alertPlatformBadge">{n.event_name}</span>
                    {n.status && <span className="muted alertAccountType">{n.status}</span>}
                  </div>

                  <p className="alertMessage">{n.message}</p>

                  <div className="alertDates">
                    <span>
                      <strong>{formatDatetime(n.created_at)}</strong>
                    </span>
                    {n.batch_id && (
                      <span className="muted">Batch: {n.batch_id}</span>
                    )}
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
