import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../context/ThemeContext";
import Sidebar from "../components/Sidebar";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
    alertNotifications: vi.fn().mockResolvedValue({
      upload_reminders: [],
      total_count: 0,
    }),
    alertNotificationsCount: vi.fn().mockResolvedValue({ total_count: 0 }),
  },
}));

const mockApi = vi.mocked(api, true);

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

  it("has no Utilities/Alerts section: Alerts is the header bell (#317)", () => {
    renderSidebar();
    expect(screen.queryByText("Utilities")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Alerts" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
  });

  it("renders primary sections without old signed-in copy or theme toggle in sidebar", () => {
    renderSidebar();
    expect(screen.queryByText("Signed in")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Toggle theme" })).not.toBeInTheDocument();
  });

  it("doesn't fetch alert counts any more (the bell reads the inbox, #317)", () => {
    renderSidebar("/wealth");
    expect(mockApi.alertNotificationsCount).not.toHaveBeenCalled();
    expect(mockApi.alertNotifications).not.toHaveBeenCalled();
  });

  it("does not use polling for alert badge refresh (no setInterval)", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    renderSidebar();
    expect(setIntervalSpy).not.toHaveBeenCalled();
    setIntervalSpy.mockRestore();
  });
});
