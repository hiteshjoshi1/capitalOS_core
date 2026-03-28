import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../context/ThemeContext";
import Sidebar from "../components/Sidebar";

vi.mock("../lib/api", () => ({
  api: {
    uploadReminderCount: vi.fn().mockResolvedValue({ count: 0 }),
  },
}));

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
    expect(screen.getByRole("link", { name: "AI Guru" })).toBeInTheDocument();
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
});
