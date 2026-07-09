import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AddAccount from "../routes/AddAccount";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";
import type { AccountOptions, Platform } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    platforms: vi.fn(),
    accounts: vi.fn(),
    accountOptions: vi.fn(),
    platformOptions: vi.fn(),
    createAccount: vi.fn(),
    createPlatform: vi.fn(),
    createCurrency: vi.fn(),
    currencies: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const platformsFixture: Platform[] = [
  { id: 1, code: "CITI", name: "Citibank", platform_type: "BANK", country: "US", website: null },
];

const optionsFixture: AccountOptions = {
  account_types: ["BANK", "BROKER"],
  currencies: ["SGD", "USD"],
  countries: ["SG", "US"],
  currency_pattern: "^[A-Z]{3}$",
};

const platformOptionsFixture = {
  platform_types: ["BANK", "BROKER"],
  countries: ["SG", "US"],
  country_pattern: "^[A-Z]{2,3}$",
};

describe("AddAccount", () => {
  afterEach(() => {
    vi.resetAllMocks();
    cleanup();
  });

  it("submits a valid account and shows success", async () => {
    mockApi.platforms.mockResolvedValueOnce(platformsFixture);
    mockApi.accountOptions.mockResolvedValueOnce(optionsFixture);
    mockApi.platformOptions.mockResolvedValueOnce(platformOptionsFixture);
    mockApi.currencies.mockResolvedValueOnce([
      { id: 1, code: "SGD", name: "Singapore Dollar", country: "Singapore" },
      { id: 2, code: "USD", name: "U.S. Dollar", country: "United States" },
    ]);
    mockApi.accounts.mockResolvedValueOnce([]);
    mockApi.createAccount.mockResolvedValueOnce({
      id: 1,
      name: "DBS Savings",
      platform: "CITI",
      platform_id: 1,
      account_type: "BANK",
      currency: "SGD",
      country: "SG",
    });
    mockApi.accounts.mockResolvedValueOnce([
      { id: 1, name: "DBS Savings", platform: "CITI", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <AddAccount />
        </MemoryRouter>
      </ThemeProvider>
    );

    const nameInput = await screen.findByLabelText("Account Name");
    await userEvent.type(nameInput, "DBS Savings");
    await userEvent.selectOptions(screen.getByLabelText("Account Platform"), "1");
    await userEvent.selectOptions(screen.getByLabelText("Account Type"), "BANK");

    const accountCard = screen.getAllByText("Account Details")[0]?.closest(".card") as HTMLElement | null;
    expect(accountCard).not.toBeNull();
    if (accountCard) {
      const scoped = within(accountCard);
      await userEvent.type(scoped.getByLabelText("Account Currency"), "sgd");
    }

    expect(screen.getByLabelText("Account Country")).toHaveValue("US");
    await userEvent.clear(screen.getByLabelText("Account Country"));
    await userEvent.type(screen.getByLabelText("Account Country"), "sg");

    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(mockApi.createAccount).toHaveBeenCalledWith({
      name: "DBS Savings",
      platform_id: 1,
      platform: "CITI",
      account_type: "BANK",
      currency: "SGD",
      country: "SG",
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Account created.");
  }, 15000);

  it("creates a new platform from the modal", async () => {
    mockApi.platforms
      .mockResolvedValueOnce(platformsFixture)
      .mockResolvedValueOnce([...platformsFixture, {
        id: 2,
        code: "PPFAS",
        name: "Parag Parikh AMC",
        platform_type: "MUTUAL_FUND",
        country: "IN",
        website: "https://www.example.com",
      }]);
    mockApi.accountOptions
      .mockResolvedValueOnce(optionsFixture)
      .mockResolvedValueOnce(optionsFixture);
    mockApi.platformOptions
      .mockResolvedValueOnce({
        ...platformOptionsFixture,
        platform_types: ["BANK", "BROKER", "MUTUAL_FUND"],
        countries: ["SG", "US", "IN"],
      })
      .mockResolvedValueOnce({
        ...platformOptionsFixture,
        platform_types: ["BANK", "BROKER", "MUTUAL_FUND"],
        countries: ["SG", "US", "IN"],
      });
    mockApi.currencies
      .mockResolvedValueOnce([
        { id: 1, code: "SGD", name: "Singapore Dollar", country: "Singapore" },
      ])
      .mockResolvedValueOnce([
        { id: 1, code: "SGD", name: "Singapore Dollar", country: "Singapore" },
      ]);
    mockApi.createPlatform.mockResolvedValueOnce({
      id: 2,
      code: "PPFAS",
      name: "Parag Parikh AMC",
      platform_type: "MUTUAL_FUND",
      country: "IN",
      website: "https://www.example.com",
    });
    mockApi.accounts.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <AddAccount />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Account Details");
    const accountCard = screen.getByText("Account Details").closest(".card");
    expect(accountCard).not.toBeNull();
    if (!accountCard) throw new Error("Account card not found");
    const addPlatformBtn = accountCard.querySelector("button.linkBtn");
    expect(addPlatformBtn).not.toBeNull();
    if (!addPlatformBtn) throw new Error("Add platform button not found");
    await userEvent.click(addPlatformBtn);

    const modal = await screen.findByRole("dialog");
    const scoped = within(modal);
    await userEvent.type(scoped.getByLabelText("Platform Code"), "PPFAS");
    await userEvent.type(scoped.getByLabelText("Platform Name"), "Parag Parikh AMC");
    await userEvent.selectOptions(scoped.getByLabelText("Platform Type"), "MUTUAL_FUND");
    await userEvent.selectOptions(scoped.getByLabelText("Platform Country"), "IN");
    await userEvent.type(scoped.getByLabelText("Platform Website"), "https://www.example.com");

    await userEvent.click(scoped.getByRole("button", { name: "Save platform" }));

    await waitFor(() => {
      expect(mockApi.createPlatform).toHaveBeenCalledWith({
        code: "PPFAS",
        name: "Parag Parikh AMC",
        platform_type: "MUTUAL_FUND",
        country: "IN",
        website: "https://www.example.com",
      });
    });
  }, 15000);

  it("renders the linked accounts directory", async () => {
    mockApi.platforms.mockResolvedValueOnce(platformsFixture);
    mockApi.accountOptions.mockResolvedValueOnce(optionsFixture);
    mockApi.platformOptions.mockResolvedValueOnce(platformOptionsFixture);
    mockApi.currencies.mockResolvedValueOnce([]);
    mockApi.accounts.mockResolvedValueOnce([
      { id: 5, name: "UOB One", platform: "UOB", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <AddAccount />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Linked accounts")).toBeInTheDocument();
    expect(screen.getByText("UOB One")).toBeInTheDocument();
    expect(screen.getByText("UOB · BANK · SGD")).toBeInTheDocument();
  });

  it("shows load error when options fail", async () => {
    mockApi.platforms.mockResolvedValueOnce(platformsFixture);
    mockApi.accountOptions.mockRejectedValueOnce(new Error("No options"));
    mockApi.platformOptions.mockResolvedValueOnce(platformOptionsFixture);
    mockApi.currencies.mockResolvedValueOnce([]);
    mockApi.accounts.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <AddAccount />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Load error")).toBeInTheDocument();
    expect(screen.getByText(/No options/)).toBeInTheDocument();
  });
});
