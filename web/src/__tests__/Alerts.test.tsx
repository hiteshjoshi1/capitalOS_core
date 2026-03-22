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
  },
}));

const mockApi = vi.mocked(api, true);

const MOCK_ALERTS = [
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
    mockApi.uploadReminderCount.mockResolvedValue({ count: 0 });
  });

  it("shows loading state initially", () => {
    mockApi.uploadReminders.mockReturnValue(new Promise(() => {}));
    renderAlerts();
    expect(screen.getByText(/Loading alerts/i)).toBeInTheDocument();
  });

  it("renders alert cards with mock data", async () => {
    mockApi.uploadReminders.mockResolvedValueOnce(MOCK_ALERTS);
    renderAlerts();

    expect(await screen.findByText("DBS Savings")).toBeInTheDocument();
    expect(screen.getByText("IBKR Brokerage")).toBeInTheDocument();
    expect(screen.getByText("DBS")).toBeInTheDocument();
    expect(screen.getByText("IBKR")).toBeInTheDocument();
    expect(screen.getByText(/45 days/)).toBeInTheDocument();
    expect(screen.getByText(/62 days/)).toBeInTheDocument();
  });

  it("shows empty state when no alerts", async () => {
    mockApi.uploadReminders.mockResolvedValueOnce([]);
    renderAlerts();

    expect(await screen.findByText(/All accounts are up to date/i)).toBeInTheDocument();
  });

  it("shows error state when API fails", async () => {
    mockApi.uploadReminders.mockRejectedValueOnce(new Error("Network error"));
    renderAlerts();

    expect(await screen.findByText(/Failed to load alerts/i)).toBeInTheDocument();
    expect(screen.getByText(/Network error/)).toBeInTheDocument();
  });

  it("each alert card includes a link to /ingest", async () => {
    mockApi.uploadReminders.mockResolvedValueOnce(MOCK_ALERTS);
    renderAlerts();

    await screen.findByText("DBS Savings");
    const ingestLinks = screen.getAllByRole("link", { name: /Go to Ingest/i });
    expect(ingestLinks.length).toBe(2);
    expect(ingestLinks[0]).toHaveAttribute("href", "/ingest");
  });

  it("shows last_transaction_date as em dash when null", async () => {
    mockApi.uploadReminders.mockResolvedValueOnce([MOCK_ALERTS[1]]);
    renderAlerts();

    await screen.findByText("IBKR Brokerage");
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("PageShell alert badge", () => {
  it("shows badge when alert count > 0", async () => {
    mockApi.uploadReminders.mockResolvedValue([]);
    mockApi.uploadReminderCount.mockResolvedValueOnce({ count: 3 });

    const { default: PageShell } = await import("../components/PageShell");
    render(
      <ThemeProvider>
        <MemoryRouter>
          <PageShell title="Test" activeRoute="/">
            <div />
          </PageShell>
        </MemoryRouter>
      </ThemeProvider>
    );

    const badge = await screen.findByLabelText(/3 upload alerts/i);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("3");
  });

  it("hides badge when alert count is 0", async () => {
    mockApi.uploadReminders.mockResolvedValue([]);
    mockApi.uploadReminderCount.mockResolvedValueOnce({ count: 0 });

    const { default: PageShell } = await import("../components/PageShell");
    render(
      <ThemeProvider>
        <MemoryRouter>
          <PageShell title="Test" activeRoute="/">
            <div />
          </PageShell>
        </MemoryRouter>
      </ThemeProvider>
    );

    // Wait for async load
    await screen.findByText("Test");
    const badge = screen.queryByLabelText(/upload alerts/i);
    expect(badge).not.toBeInTheDocument();
  });
});
