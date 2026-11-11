// Data Hub: inbox, sources, reminders, alerts: API calls (split out of lib/api.ts, #368).
import { req } from "../http";
import type { DataHubSummary, InboxResponse, SourceFreshness, SourceFreshnessRow, UnifiedAlertsCount, UnifiedAlertsResponse, UploadReminder, UploadReminderCount } from "../types/dataHub";

export const dataHubClient = {
  dataHubSummary: () => req<DataHubSummary>("/dashboard/data-hub-summary"),
  operationsInbox: () => req<InboxResponse>("/operations/inbox"),
  sourceFreshness: () => req<SourceFreshness>("/dashboard/source-freshness"),
  setSourceFreshnessCadence: (sourceKey: string, body: { cadence: string; grace_days: number }) =>
    req<SourceFreshnessRow>(`/dashboard/source-freshness/${encodeURIComponent(sourceKey)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  resetSourceFreshnessCadence: (sourceKey: string) =>
    req<SourceFreshnessRow>(`/dashboard/source-freshness/${encodeURIComponent(sourceKey)}`, { method: "DELETE" }),
  uploadReminders: (month?: string) =>
    req<UploadReminder[]>(`/alerts/upload-reminders${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  uploadReminderCount: (month?: string) =>
    req<UploadReminderCount>(`/alerts/upload-reminders/count${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  alertNotifications: (month?: string) =>
    req<UnifiedAlertsResponse>(`/alerts/notifications${month ? `?month=${encodeURIComponent(month)}` : ""}`),
  alertNotificationsCount: (month?: string) =>
    req<UnifiedAlertsCount>(`/alerts/notifications/count${month ? `?month=${encodeURIComponent(month)}` : ""}`),
};
