import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Alerts from "../routes/Alerts";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    uploadReminders: vi.fn(),
    uploadReminderCount: vi.fn(),
    alertNotifications: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

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

const EMPTY_NOTIFICATIONS = {
  upload_reminders: [],
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

  it("shows empty state when no alerts", async () => {
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

  it("each upload reminder card links to ingest with the reminder account selected", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: MOCK_REMINDERS,
      total_count: 2,
    });
    renderAlerts();

    await screen.findByText("DBS Savings");
    const ingestLinks = screen.getAllByRole("link", { name: /Go to Ingest/i });
    expect(ingestLinks.length).toBe(2);
    expect(ingestLinks[0]).toHaveAttribute("href", "/ingest?account_id=1");
    expect(ingestLinks[1]).toHaveAttribute("href", "/ingest?account_id=2");
  });

  it("shows last_transaction_date as em dash when null", async () => {
    mockApi.alertNotifications.mockResolvedValueOnce({
      upload_reminders: [MOCK_REMINDERS[1]],
      total_count: 1,
    });
    renderAlerts();

    await screen.findByText("IBKR Brokerage");
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("does not use polling (no setInterval)", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    renderAlerts();
    expect(setIntervalSpy).not.toHaveBeenCalled();
    setIntervalSpy.mockRestore();
  });
});
