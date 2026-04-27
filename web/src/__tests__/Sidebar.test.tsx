import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

function renderSidebar(initialPath = "/") {
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

  it("renders Dashboard and Settings top-level links", () => {
    renderSidebar();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("renders all IA section toggle buttons", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: /Wealth/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Liabilities/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Intelligence/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Operations/i })).toBeInTheDocument();
  });

  it("highlights Dashboard link as active on / route", () => {
    renderSidebar("/");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveClass("sidebarLinkActive");
  });

  it("highlights Settings link as active on /settings route", () => {
    renderSidebar("/settings");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveClass("sidebarLinkActive");
  });

  it("auto-expands Wealth section when active child route is /holdings", () => {
    renderSidebar("/holdings");
    expect(screen.getByRole("link", { name: "Stocks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stocks" })).toHaveClass("sidebarLinkActive");
  });

  it("auto-expands Operations section when active child route is /ingest", () => {
    renderSidebar("/ingest");
    expect(screen.getByRole("link", { name: "Ingest" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ingest" })).toHaveClass("sidebarLinkActive");
  });

  it("toggles a section open and closed on button click", async () => {
    const user = userEvent.setup();
    renderSidebar("/");

    // Wealth section should be closed on / route
    const wealthToggle = screen.getByRole("button", { name: /Wealth/i });
    expect(wealthToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Stocks" })).not.toBeInTheDocument();

    await user.click(wealthToggle);
    expect(wealthToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Stocks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dividends" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crypto" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cash" })).toBeInTheDocument();

    await user.click(wealthToggle);
    expect(wealthToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Stocks" })).not.toBeInTheDocument();
  });

  it("renders Liabilities children when section is expanded", async () => {
    const user = userEvent.setup();
    renderSidebar("/");

    const toggle = screen.getByRole("button", { name: /Liabilities/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Credit Cards" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Loans" })).toBeInTheDocument();
  });

  it("renders Intelligence children when section is expanded", async () => {
    const user = userEvent.setup();
    renderSidebar("/");

    const toggle = screen.getByRole("button", { name: /Intelligence/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Companies" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Sage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Author Library" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "AI Guru" })).not.toBeInTheDocument();
  });

  it("renders Operations children when section is expanded", async () => {
    const user = userEvent.setup();
    renderSidebar("/");

    const toggle = screen.getByRole("button", { name: /Operations/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Platforms" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crypto Wallets" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ingest" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Market Data" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Author Sources" })).toBeInTheDocument();
  });

  it("non-active sections start collapsed on /holdings route", () => {
    renderSidebar("/holdings");
    expect(screen.getByRole("button", { name: /Wealth/i })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /Liabilities/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /Intelligence/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /Operations/i })).toHaveAttribute("aria-expanded", "false");
  });

  it("renders user area with theme toggle button", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeInTheDocument();
    expect(screen.getByText("User")).toBeInTheDocument();
  });

  it("theme toggle button reflects current theme", async () => {
    const user = userEvent.setup();
    renderSidebar();

    const toggle = screen.getByRole("button", { name: "Toggle theme" });
    expect(toggle).toHaveTextContent("Dark");

    await user.click(toggle);
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(toggle).toHaveTextContent("Light");
  });

  it("shows no alert badge when alertNotifications returns total_count 0", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [],
      system_notifications: [],
      total_count: 0,
    });
    renderSidebar("/alerts");
    await waitFor(() => {
      expect(screen.queryByLabelText(/alerts/i)).not.toBeInTheDocument();
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
