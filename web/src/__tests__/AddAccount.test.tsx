import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AddAccount from "../routes/AddAccount";
import { api } from "../lib/api";
import type { AccountOptions, Platform } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    platforms: vi.fn(),
    accountOptions: vi.fn(),
    platformOptions: vi.fn(),
    createAccount: vi.fn(),
    createPlatform: vi.fn(),
    createCurrency: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const platformsFixture: Platform[] = [
  { id: 1, code: "DBS", name: "DBS Bank", platform_type: "BANK", country: "SG", website: null },
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
  });

  it("submits a valid account and shows success", async () => {
    mockApi.platforms.mockResolvedValueOnce(platformsFixture);
    mockApi.accountOptions.mockResolvedValueOnce(optionsFixture);
    mockApi.platformOptions.mockResolvedValueOnce(platformOptionsFixture);
    mockApi.createAccount.mockResolvedValueOnce({
      id: 1,
      name: "DBS Savings",
      platform: "DBS",
      platform_id: 1,
      account_type: "BANK",
      currency: "SGD",
      country: "SG",
    });

    render(
      <MemoryRouter>
        <AddAccount />
      </MemoryRouter>
    );

    const nameInput = await screen.findByLabelText("Account Name");
    await userEvent.type(nameInput, "DBS Savings");
    await userEvent.selectOptions(screen.getByLabelText("Account Platform"), "1");
    await userEvent.selectOptions(screen.getByLabelText("Account Type"), "BANK");

    const accountCard = screen.getByText("Account Details").closest(".card");
    expect(accountCard).not.toBeNull();
    if (accountCard) {
      const scoped = within(accountCard);
      const currencySelect = scoped.getByLabelText("Account Currency");
      await userEvent.selectOptions(currencySelect, "SGD");
    }

    expect(screen.getByLabelText("Account Country")).toHaveValue("SG");

    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(mockApi.createAccount).toHaveBeenCalledWith({
      name: "DBS Savings",
      platform_id: 1,
      platform: "DBS",
      account_type: "BANK",
      currency: "SGD",
      country: "SG",
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Account created.");
  });

  it("shows load error when options fail", async () => {
    mockApi.platforms.mockResolvedValueOnce(platformsFixture);
    mockApi.accountOptions.mockRejectedValueOnce(new Error("No options"));
    mockApi.platformOptions.mockResolvedValueOnce(platformOptionsFixture);

    render(
      <MemoryRouter>
        <AddAccount />
      </MemoryRouter>
    );

    expect(await screen.findByText("Load error")).toBeInTheDocument();
    expect(screen.getByText(/No options/)).toBeInTheDocument();
  });
});
