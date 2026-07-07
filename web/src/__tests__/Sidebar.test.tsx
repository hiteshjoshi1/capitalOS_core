import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../context/ThemeContext";
import Sidebar from "../components/Sidebar";
import { api } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import type { RagAuthorIngestionEventPayload, RealtimeEventEnvelope } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
    alertNotifications: vi.fn().mockResolvedValue({
      upload_reminders: [],
      system_notifications: [],
      total_count: 0,
    }),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn().mockReturnValue(() => {}),
}));

const mockApi = vi.mocked(api, true);
const mockSubscribe = vi.mocked(subscribeToRealtimeTopic);

function renderSidebar(initialPath = "/wealth") {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Sidebar />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders the brand and primary sections without a Dashboard link", () => {
    renderSidebar();
    expect(screen.getByRole("link", { name: /CapitalOS/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wealth" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cash Flow" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Liabilities" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Data Hub" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Research" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("highlights Wealth as the active primary section on wealth child routes", () => {
    renderSidebar("/holdings");
    expect(screen.getByRole("link", { name: "Wealth" })).toHaveClass("sidebarLinkActive");
    expect(screen.getByRole("link", { name: "Data Hub" })).not.toHaveClass("sidebarLinkActive");
  });

  it("highlights Cash Flow as the active primary section on cash-flow routes", () => {
    renderSidebar("/cash-flow");
    expect(screen.getByRole("link", { name: "Cash Flow" })).toHaveClass("sidebarLinkActive");
    expect(screen.getByRole("link", { name: "Wealth" })).not.toHaveClass("sidebarLinkActive");
  });

  it("highlights Operations as the active primary section on operational routes", () => {
    renderSidebar("/market-data");
    expect(screen.getByRole("link", { name: "Data Hub" })).toHaveClass("sidebarLinkActive");
  });

  it("renders Alerts in the utility links and omits Settings", () => {
    renderSidebar();
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
  });

  it("renders primary sections without old signed-in copy or theme toggle in sidebar", () => {
    renderSidebar();
    expect(screen.queryByText("Signed in")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Toggle theme" })).not.toBeInTheDocument();
  });

  it("shows no alert badge when alertNotifications returns total_count 0", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [],
      system_notifications: [],
      total_count: 0,
    });
    renderSidebar("/alerts");
    await waitFor(() => {
      expect(screen.queryByLabelText(/\d+ alerts/i)).not.toBeInTheDocument();
    });
  });

  it("shows alert badge when alertNotifications returns total_count > 0", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [{ account_id: 1 } as never],
      system_notifications: [],
      total_count: 1,
    });
    renderSidebar("/alerts");
    await waitFor(() => {
      expect(screen.getByLabelText(/1 alerts/i)).toBeInTheDocument();
    });
  });

  it("rehydrates badge count from backend when realtime event arrives", async () => {
    let capturedOnEvent: ((event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>) => void) | undefined;
    mockSubscribe.mockImplementation((_topic, handlers) => {
      capturedOnEvent = handlers.onEvent as typeof capturedOnEvent;
      return () => {};
    });

    mockApi.alertNotifications
      .mockResolvedValueOnce({
        upload_reminders: [],
        system_notifications: [],
        total_count: 0,
      })
      .mockResolvedValueOnce({
        upload_reminders: [],
        system_notifications: [{ id: "sys-1" } as never],
        total_count: 1,
      });

    renderSidebar("/alerts");
    await waitFor(() => expect(screen.queryByLabelText(/0 alerts/i)).not.toBeInTheDocument());

    const event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload> = {
      id: "ws-event-1",
      topic: "author-ingestion",
      event_name: "source_ingested",
      author_id: "test-author",
      source_id: "src-1",
      job_id: "job-1",
      batch_id: "batch-1",
      status: "ingested",
      created_at: "2025-12-01T10:00:00Z",
      payload: {} as RagAuthorIngestionEventPayload,
    };

    act(() => {
      capturedOnEvent?.(event);
    });

    await waitFor(() => {
      expect(mockApi.alertNotifications).toHaveBeenCalledTimes(2);
      expect(screen.getByLabelText(/1 alerts/i)).toBeInTheDocument();
    });
  });

  it("rehydrates alert badge count from backend on realtime reconnect", async () => {
    let capturedOnStatusChange: ((status: string) => void) | undefined;
    mockSubscribe.mockImplementation((_topic, handlers) => {
      capturedOnStatusChange = handlers.onStatusChange as typeof capturedOnStatusChange;
      return () => {};
    });

    mockApi.alertNotifications
      .mockResolvedValueOnce({
        upload_reminders: [],
        system_notifications: [],
        total_count: 1,
      })
      .mockResolvedValueOnce({
        upload_reminders: [],
        system_notifications: [],
        total_count: 4,
      });

    renderSidebar("/alerts");
    await waitFor(() => {
      expect(screen.getByLabelText(/1 alerts/i)).toBeInTheDocument();
    });

    await act(async () => {
      capturedOnStatusChange?.("disconnected");
      capturedOnStatusChange?.("connected");
      await Promise.resolve();
    });

    expect(mockApi.alertNotifications.mock.calls.length).toBeGreaterThanOrEqual(2);
    await waitFor(() => {
      expect(screen.getByLabelText(/4 alerts/i)).toBeInTheDocument();
    });
  });

  it("does not use polling for alert badge refresh (no setInterval)", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    renderSidebar();
    expect(setIntervalSpy).not.toHaveBeenCalled();
    setIntervalSpy.mockRestore();
  });

  it("subscribes to author-ingestion realtime topic on mount", () => {
    renderSidebar();
    expect(mockSubscribe).toHaveBeenCalledWith("author-ingestion", expect.objectContaining({ onEvent: expect.any(Function) }));
  });

  it("unsubscribes from realtime on unmount", () => {
    const unsubscribe = vi.fn();
    mockSubscribe.mockReturnValue(unsubscribe);
    const { unmount } = renderSidebar();
    unmount();
    expect(unsubscribe).toHaveBeenCalled();
  });
});
