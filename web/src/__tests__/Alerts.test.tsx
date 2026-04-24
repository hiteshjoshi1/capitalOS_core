import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Alerts from "../routes/Alerts";
import { api } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import { ThemeProvider } from "../context/ThemeContext";
import type { RagAuthorIngestionEventPayload, RealtimeEventEnvelope } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    uploadReminders: vi.fn(),
    uploadReminderCount: vi.fn(),
    alertNotifications: vi.fn(),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn(),
}));

const mockApi = vi.mocked(api, true);
const mockSubscribe = vi.mocked(subscribeToRealtimeTopic);

const MOCK_REMINDERS = [
  {
    account_id: 1,
    account_name: "DBS Savings",
    platform: "DBS",
    account_type: "BANK",
    last_upload_date: "2025-11-01",
    last_transaction_date: "2025-10-31",
    days_since_upload: 45,
    message: "Upload the latest statement for DBS Savings (DBS). Last upload was 2025-11-01 and last transaction tracked was 2025-10-31.",
  },
  {
    account_id: 2,
    account_name: "IBKR Brokerage",
    platform: "IBKR",
    account_type: "BROKER",
    last_upload_date: "2025-10-15",
    last_transaction_date: null,
    days_since_upload: 62,
    message: "Upload the latest statement for IBKR Brokerage (IBKR). Last upload was 2025-10-15.",
  },
];

const MOCK_SYSTEM_NOTIFICATIONS = [
  {
    id: "event-1",
    alert_type: "system_notification" as const,
    topic: "author-ingestion",
    event_name: "batch_completed",
    author_id: "warren_buffett",
    source_id: null,
    job_id: null,
    batch_id: "batch-abc",
    status: "done",
    message: "Ingestion batch completed for Warren Buffett: 5/5 sources ingested.",
    created_at: "2025-12-01T10:00:00.000Z",
    payload: {},
  },
];

const EMPTY_NOTIFICATIONS = {
  upload_reminders: [],
  system_notifications: [],
  total_count: 0,
};

function renderAlerts() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <Alerts />
      </MemoryRouter>
    </ThemeProvider>
  );
}

describe("Alerts page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSubscribe.mockReturnValue(() => {});
    mockApi.alertNotifications.mockResolvedValue(EMPTY_NOTIFICATIONS);
  });

  it("shows loading state initially", () => {
    mockApi.alertNotifications.mockReturnValue(new Promise(() => {}));
    renderAlerts();
    expect(screen.getByText(/Loading alerts/i)).toBeInTheDocument();
  });

  it("renders upload reminder cards with mock data", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: MOCK_REMINDERS,
      system_notifications: [],
      total_count: 2,
    });
    renderAlerts();

    expect(await screen.findByText("DBS Savings")).toBeInTheDocument();
    expect(screen.getByText("IBKR Brokerage")).toBeInTheDocument();
    expect(screen.getByText("DBS")).toBeInTheDocument();
    expect(screen.getByText("IBKR")).toBeInTheDocument();
    expect(screen.getByText(/45 days/)).toBeInTheDocument();
    expect(screen.getByText(/62 days/)).toBeInTheDocument();
  });

  it("renders system notification cards with mock data", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [],
      system_notifications: MOCK_SYSTEM_NOTIFICATIONS,
      total_count: 1,
    });
    renderAlerts();

    expect(await screen.findByRole("heading", { name: /System Notifications/i })).toBeInTheDocument();
    expect(screen.getByText("warren_buffett")).toBeInTheDocument();
    expect(screen.getByText(/Ingestion batch completed for Warren Buffett/i)).toBeInTheDocument();
  });

  it("shows empty state when no alerts and no system notifications", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce(EMPTY_NOTIFICATIONS);
    renderAlerts();

    expect(await screen.findByText(/All accounts are up to date/i)).toBeInTheDocument();
  });

  it("shows error state when API fails", async () => {
    mockApi.alertNotifications.mockRejectedValueOnce(new Error("Network error"));
    renderAlerts();

    expect(await screen.findByText(/Failed to load alerts/i)).toBeInTheDocument();
    expect(screen.getByText(/Network error/)).toBeInTheDocument();
  });

  it("each upload reminder card includes a link to /ingest", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: MOCK_REMINDERS,
      system_notifications: [],
      total_count: 2,
    });
    renderAlerts();

    await screen.findByText("DBS Savings");
    const ingestLinks = screen.getAllByRole("link", { name: /Go to Ingest/i });
    expect(ingestLinks.length).toBe(2);
    expect(ingestLinks[0]).toHaveAttribute("href", "/ingest");
  });

  it("shows last_transaction_date as em dash when null", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [MOCK_REMINDERS[1]],
      system_notifications: [],
      total_count: 1,
    });
    renderAlerts();

    await screen.findByText("IBKR Brokerage");
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("subscribes to author-ingestion realtime topic on mount", () => {
    renderAlerts();
    expect(mockSubscribe).toHaveBeenCalledWith("author-ingestion", expect.objectContaining({ onEvent: expect.any(Function) }));
  });

  it("unsubscribes from realtime on unmount", () => {
    const unsubscribe = vi.fn();
    mockSubscribe.mockReturnValue(unsubscribe);
    const { unmount } = renderAlerts();
    unmount();
    expect(unsubscribe).toHaveBeenCalled();
  });

  it("does not use polling (no setInterval)", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    renderAlerts();
    expect(setIntervalSpy).not.toHaveBeenCalled();
    setIntervalSpy.mockRestore();
  });

  it("prepends new system notification when realtime event arrives", async () => {
    let capturedOnEvent: ((event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>) => void) | undefined;
    mockSubscribe.mockImplementation((_topic, handlers) => {
      capturedOnEvent = handlers.onEvent as typeof capturedOnEvent;
      return () => {};
    });

    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [],
      system_notifications: [],
      total_count: 0,
    });

    renderAlerts();
    await waitFor(() => expect(screen.queryByText(/Loading alerts/i)).not.toBeInTheDocument());

    const realtimeEvent: RealtimeEventEnvelope<RagAuthorIngestionEventPayload> = {
      id: "ws-event-1",
      topic: "author-ingestion",
      event_name: "source_ingested",
      author_id: "charlie_munger",
      source_id: "src-1",
      job_id: "job-1",
      batch_id: "batch-xyz",
      status: "ingested",
      created_at: "2025-12-02T10:00:00.000Z",
      payload: {
        author: { id: "charlie_munger", name: "Charlie Munger" },
        source: { id: "src-1", url: "https://example.com/article", source_type: "html", status: "ingested", author_id: "charlie_munger", hash: null, last_ingested_at: null, created_at: "2025-12-01T00:00:00Z" },
        job: { id: "job-1", source_id: "src-1", batch_id: "batch-xyz", status: "done", failure_category: null, error: null, stats_json: {}, started_at: null, finished_at: null, created_at: "2025-12-01T00:00:00Z" },
        batch: { id: "batch-xyz", status: "done" },
      },
    };

    act(() => {
      capturedOnEvent?.(realtimeEvent);
    });

    expect(await screen.findByRole("heading", { name: /System Notifications/i })).toBeInTheDocument();
    expect(screen.getByText(/Successfully ingested source for Charlie Munger/i)).toBeInTheDocument();
  });

  it("reconnect: page shows previously-loaded alerts after realtime reconnect", async () => {
    let capturedOnStatusChange: ((status: string) => void) | undefined;
    mockSubscribe.mockImplementation((_topic, handlers) => {
      capturedOnStatusChange = handlers.onStatusChange as typeof capturedOnStatusChange;
      return () => {};
    });

    mockApi.alertNotifications
      .mockResolvedValueOnce({
        upload_reminders: MOCK_REMINDERS,
        system_notifications: [],
        total_count: 2,
      })
      .mockResolvedValueOnce({
        upload_reminders: [],
        system_notifications: MOCK_SYSTEM_NOTIFICATIONS,
        total_count: 1,
      });

    renderAlerts();
    await screen.findByText("DBS Savings");

    await act(async () => {
      capturedOnStatusChange?.("disconnected");
      capturedOnStatusChange?.("connected");
      await Promise.resolve();
    });

    expect(mockApi.alertNotifications.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(await screen.findByRole("heading", { name: /System Notifications/i })).toBeInTheDocument();
    expect(screen.getByText(/Ingestion batch completed for Warren Buffett/i)).toBeInTheDocument();
  });
});
