import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Platforms from "../routes/Platforms";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    platforms: vi.fn(),
    platformOptions: vi.fn(),
    createPlatform: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

describe("Platforms", () => {
  it("renders existing platform rows", async () => {
    mockApi.platforms.mockResolvedValueOnce([
      { id: 1, code: "IBKR", name: "Interactive Brokers", platform_type: "BROKER", country: "US", website: null },
    ]);
    mockApi.platformOptions.mockResolvedValueOnce({
      platform_types: ["BANK", "BROKER"],
      countries: ["SG", "US"],
      country_pattern: "^[A-Z]{2,3}$",
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Platforms />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Add Platform" })).toBeInTheDocument();
    expect(screen.getByText("Interactive Brokers")).toBeInTheDocument();
    expect(screen.getByText("IBKR · BROKER · US")).toBeInTheDocument();
  });

  it("creates a platform and shows success", async () => {
    mockApi.platforms
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        { id: 2, code: "DBS", name: "DBS Bank", platform_type: "BANK", country: "SG", website: "https://www.dbs.com" },
      ]);
    mockApi.platformOptions
      .mockResolvedValueOnce({
        platform_types: ["BANK", "BROKER"],
        countries: ["SG", "US"],
        country_pattern: "^[A-Z]{2,3}$",
      })
      .mockResolvedValueOnce({
        platform_types: ["BANK", "BROKER"],
        countries: ["SG", "US"],
        country_pattern: "^[A-Z]{2,3}$",
      });
    mockApi.createPlatform.mockResolvedValueOnce({
      id: 2,
      code: "DBS",
      name: "DBS Bank",
      platform_type: "BANK",
      country: "SG",
      website: "https://www.dbs.com",
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Platforms />
        </MemoryRouter>
      </ThemeProvider>,
    );

    await screen.findByText("New Platform");

    await userEvent.type(screen.getByLabelText("Platform Code"), "dbs");
    await userEvent.type(screen.getByLabelText("Platform Name"), "DBS Bank");
    await userEvent.selectOptions(screen.getByLabelText("Platform Type"), "BANK");
    await userEvent.selectOptions(screen.getByLabelText("Platform Country"), "SG");
    await userEvent.type(screen.getByLabelText("Platform Website"), "https://www.dbs.com");
    await userEvent.click(screen.getByRole("button", { name: "Save platform" }));

    expect(mockApi.createPlatform).toHaveBeenCalledWith({
      code: "DBS",
      name: "DBS Bank",
      platform_type: "BANK",
      country: "SG",
      website: "https://www.dbs.com",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Platform saved.");
  });
});
