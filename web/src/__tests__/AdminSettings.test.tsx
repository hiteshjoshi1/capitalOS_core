import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AdminSettings from "../routes/AdminSettings";
import Settings from "../routes/Settings";
import { api } from "../lib/api";
import type { DataHubSummary } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    dataHubSummary: vi.fn(),
    platforms: vi.fn(),
    platformOptions: vi.fn(),
    createPlatform: vi.fn(),
    cryptoAllowlist: vi.fn(),
    cryptoAllowlistAdd: vi.fn(),
  },
}));

const authState = { user: { id: 1, username: "demo", is_admin: true } };
vi.mock("../context/useAuth", () => ({ useAuth: () => authState }));
// Settings' other cards call APIs this test doesn't care about.
vi.mock("../components/HomeRegionCard", () => ({ default: () => null }));
vi.mock("../components/RiskThresholdsCard", () => ({ default: () => null }));
vi.mock("../components/ChangePasswordCard", () => ({ default: () => null }));

const mockApi = vi.mocked(api, true);

function renderAt(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/admin" element={<AdminSettings />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("Settings → Admin (#321)", () => {
  beforeEach(() => {
    clearApiCache();
    vi.clearAllMocks();
    authState.user.is_admin = true;
    mockApi.dataHubSummary.mockResolvedValue({
      job_status: [
        { job: "ibkr_flex", label: "IBKR Flex", state: "failing", failure_threshold: 3, consecutive_failures: 3,
          last_run_at: "2026-11-08T01:00:00Z", last_success_at: null, last_error: "token expired", scopes: [] },
        { job: "fx", label: "FX rates", state: "ok", failure_threshold: 3, consecutive_failures: 0, scopes: [] },
      ],
    } as unknown as DataHubSummary);
    mockApi.platforms.mockResolvedValue([]);
    mockApi.platformOptions.mockResolvedValue({ platform_types: ["BANK"], countries: ["SG"], country_pattern: "^[A-Z]{2,3}$" });
    mockApi.cryptoAllowlist.mockResolvedValue([]);
  });

  it("shows jobs, the platform directory and the token allowlist to an admin", async () => {
    renderAt("/settings/admin");
    expect(await screen.findByRole("heading", { name: "Jobs" })).toBeInTheDocument();
    expect(await screen.findByText("token expired")).toBeInTheDocument();
    expect(screen.getByText(/3 failed in a row/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Platform directory" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Token allowlist" })).toBeInTheDocument();
  });

  it("sends a non-admin back to Settings, which has no Admin link", async () => {
    authState.user.is_admin = false;
    renderAt("/settings/admin");
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open admin" })).not.toBeInTheDocument();
  });

  it("links an admin from Settings to Admin", async () => {
    renderAt("/settings");
    expect(await screen.findByRole("link", { name: "Open admin" })).toHaveAttribute("href", "/settings/admin");
  });

  it("validates and adds an allowlist token, with fallback labels (moved from the wallets page)", async () => {
    mockApi.cryptoAllowlist.mockResolvedValueOnce([
      { id: 1, chain: "ethereum", contract_address: "0xabc", symbol: null, name: null },
    ]);
    mockApi.cryptoAllowlistAdd.mockResolvedValue({ id: 2, chain: "ethereum", contract_address: "0xdef", symbol: "DEF", name: "Delta" });
    const user = userEvent.setup();
    renderAt("/settings/admin");
    expect((await screen.findAllByText("—")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Add token" }));
    expect(await screen.findByText("Contract address is required.")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("0x..."), "0xdef");
    await user.click(screen.getByRole("button", { name: "Add token" }));
    await waitFor(() => expect(mockApi.cryptoAllowlistAdd).toHaveBeenCalledWith({ chain: "ethereum", contract_address: "0xdef" }));
    expect(await screen.findByText("DEF")).toBeInTheDocument();
  });
});
