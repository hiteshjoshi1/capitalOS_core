import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import AddFlow from "../routes/AddFlow";
import { api, UploadRefusedError } from "../lib/api";
import type { AccountOptions, Platform } from "../lib/api";
import { clearApiCache } from "../lib/useApiResource";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    UploadRefusedError: actual.UploadRefusedError,
    api: {
      platforms: vi.fn(),
      accounts: vi.fn(),
      accountOptions: vi.fn(),
      platformOptions: vi.fn(),
      createAccount: vi.fn(),
      createPlatform: vi.fn(),
      ingestUpload: vi.fn(),
    },
  };
});

// The wallet step's Solana stack is covered by WalletConnectForm/WalletLazyLoad tests.
vi.mock("../wallet/WalletConnectStep.tsx", () => ({
  default: ({ chainType, label, onVerified }: { chainType: string; label: string; onVerified: (m: string) => void }) => (
    <button type="button" onClick={() => onVerified("Wallet w9 verified")}>
      mock sign {chainType} {label}
    </button>
  ),
}));

const authState = { user: { id: 1, username: "hitesh", is_admin: true } };
vi.mock("../context/useAuth", () => ({ useAuth: () => authState }));

const mockApi = vi.mocked(api, true);

const platformsFixture: Platform[] = [
  { id: 1, code: "CITI", name: "Citibank", platform_type: "BANK", country: "SG", website: null },
  { id: 2, code: "IBKR", name: "Interactive Brokers", platform_type: "BROKER", country: "US", website: null },
  { id: 3, code: "AMEX", name: "American Express", platform_type: "CARD_ISSUER", country: "SG", website: null },
];

const optionsFixture: AccountOptions = {
  account_types: ["BANK", "BROKER", "EXCHANGE", "WALLET", "CREDIT_CARD", "LOAN", "MUTUAL_FUND"],
  currencies: ["SGD", "USD"],
  countries: ["SG", "US"],
  currency_pattern: "^[A-Z]{3}$",
};

function renderFlow(path = "/add") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AddFlow />
    </MemoryRouter>,
  );
}

describe("AddFlow (+ Add stepper, #319)", () => {
  beforeEach(() => {
    clearApiCache();
    authState.user.is_admin = true;
    Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true, writable: true });
    mockApi.platforms.mockResolvedValue(platformsFixture);
    mockApi.accountOptions.mockResolvedValue(optionsFixture);
    mockApi.platformOptions.mockResolvedValue({
      platform_types: ["BANK", "BROKER", "EXCHANGE", "CARD_ISSUER", "WALLET_PROVIDER"],
      countries: ["SG", "US"],
      country_pattern: "^[A-Z]{2,3}$",
    });
    mockApi.accounts.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.resetAllMocks();
    cleanup();
  });

  it("a new card account and its first upload in one flow", async () => {
    mockApi.createAccount.mockResolvedValueOnce({
      id: 42,
      name: "Citibank Credit card",
      platform: "CITI",
      platform_id: 1,
      account_type: "CREDIT_CARD",
      currency: "SGD",
      country: "SG",
    });
    mockApi.ingestUpload.mockResolvedValueOnce({ job_id: 7, status: "IMPORTED", counts: { transactions_inserted: 12 } });
    const user = userEvent.setup();
    renderFlow();

    await user.click(await screen.findByRole("radio", { name: /Credit card/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    // Card issuers and banks fit a card; the broker is one tick away.
    expect(await screen.findByRole("heading", { name: /Where is it\?/ })).toHaveFocus();
    expect(screen.getByRole("radio", { name: /American Express/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Interactive Brokers/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Citibank/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    // Defaults come from the platform.
    expect(screen.getByLabelText("Name")).toHaveValue("Citibank Credit card");
    expect(screen.getByLabelText("Currency")).toHaveValue("SGD");
    expect(screen.getByLabelText("Country (optional)")).toHaveValue("SG");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(mockApi.createAccount).toHaveBeenCalledWith({
        name: "Citibank Credit card",
        platform_id: 1,
        platform: "CITI",
        account_type: "CREDIT_CARD",
        currency: "SGD",
        country: "SG",
      }),
    );
    expect(await screen.findByText(/Citibank Credit card created/)).toBeInTheDocument();
    // The account exists now: no going back to steps 1-3.
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();

    const file = new File(["a,b"], "citi_2026-10-19.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Statement file"), file);
    expect(screen.getByLabelText("Statement date (optional)")).toHaveValue("2026-10-19");
    await user.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(mockApi.ingestUpload).toHaveBeenCalledWith(42, file, "2026-10-19"));
    expect(await screen.findByText("Imported: 12 transactions saved.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the import report" })).toHaveAttribute("href", "/ingest?job=7");
    expect(screen.getByRole("link", { name: "Done" })).toHaveAttribute("href", "/operations/sources");
  });

  it("says what's missing instead of a dead button", async () => {
    const user = userEvent.setup();
    renderFlow();

    await user.click(await screen.findByRole("button", { name: "Next" }));
    expect(screen.getByRole("alert")).toHaveTextContent("To continue: choose what you're adding.");

    await user.click(screen.getByRole("radio", { name: /Bank account/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("alert")).toHaveTextContent("To continue: pick where the account is (a platform).");

    await user.click(screen.getByRole("radio", { name: /Citibank/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.clear(screen.getByLabelText("Name"));
    await user.clear(screen.getByLabelText("Currency"));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "To create the account: add a name and a 3-letter currency (e.g. SGD).",
    );
    expect(mockApi.createAccount).not.toHaveBeenCalled();
  });

  it("asks for the file before uploading, and offers to skip", async () => {
    mockApi.createAccount.mockResolvedValueOnce({
      id: 5, name: "IBKR", platform: "IBKR", platform_id: 2, account_type: "BROKER", currency: "USD", country: "US",
    });
    const user = userEvent.setup();
    renderFlow("/add?what=broker");

    // ?what= starts at "where".
    await user.click(await screen.findByRole("radio", { name: /Interactive Brokers/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("Currency")).toHaveValue("USD");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await user.click(await screen.findByRole("button", { name: "Upload" }));
    expect(screen.getByRole("alert")).toHaveTextContent("To upload: choose the statement file.");
    expect(mockApi.ingestUpload).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Skip for now" })).toHaveAttribute("href", "/operations/sources");
  });

  it("shows a refused upload and can upload anyway", async () => {
    mockApi.createAccount.mockResolvedValueOnce({
      id: 9, name: "Citibank Bank account", platform: "CITI", platform_id: 1, account_type: "BANK", currency: "SGD", country: "SG",
    });
    mockApi.ingestUpload
      .mockRejectedValueOnce(
        new UploadRefusedError({
          code: "statement_account_mismatch",
          message: "This statement is for account …1234, not …9876.",
          override_field: "allow_account_mismatch",
        }),
      )
      .mockResolvedValueOnce({ job_id: 3, status: "NEEDS_MAPPING" });
    const user = userEvent.setup();
    renderFlow("/add?what=bank");

    await user.click(await screen.findByRole("radio", { name: /Citibank/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await user.upload(await screen.findByLabelText("Statement file"), new File(["x"], "s.csv"));
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText(/not …9876/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Upload anyway" }));
    await waitFor(() =>
      expect(mockApi.ingestUpload).toHaveBeenLastCalledWith(9, expect.any(File), undefined, { allowAccountMismatch: true }),
    );
    expect(await screen.findByText(/doesn't know this file's format/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the import report" })).toHaveAttribute("href", "/ingest?job=3");
  });

  it("adds a platform inline (admin), with its code derived from the name", async () => {
    mockApi.createPlatform.mockResolvedValueOnce({
      id: 4, code: "TRUST_BANK", name: "Trust Bank", platform_type: "BANK", country: "SG", website: null,
    });
    mockApi.platforms.mockResolvedValueOnce(platformsFixture).mockResolvedValueOnce([
      ...platformsFixture,
      { id: 4, code: "TRUST_BANK", name: "Trust Bank", platform_type: "BANK", country: "SG", website: null },
    ]);
    const user = userEvent.setup();
    renderFlow("/add?what=bank");

    await user.click(await screen.findByRole("button", { name: "Not listed? Add a platform" }));
    await user.type(screen.getByLabelText("Platform Name"), "Trust Bank");
    expect(screen.getByLabelText("Platform Code")).toHaveValue("TRUST_BANK");
    expect(screen.getByLabelText("Platform Type")).toHaveValue("BANK");
    await user.click(screen.getByRole("button", { name: "Add platform" }));

    await waitFor(() =>
      expect(mockApi.createPlatform).toHaveBeenCalledWith({
        code: "TRUST_BANK", name: "Trust Bank", platform_type: "BANK", country: "SG", website: null,
      }),
    );
    // The new platform is picked.
    expect(await screen.findByRole("radio", { name: /Trust Bank/ })).toBeChecked();
  });

  it("tells a non-admin who adds platforms", async () => {
    authState.user.is_admin = false;
    renderFlow("/add?what=bank");
    expect(await screen.findByText(/an admin adds them in Settings → Admin/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Not listed? Add a platform" })).not.toBeInTheDocument();
  });

  it("adds a wallet: chain, name, then connect and sign", async () => {
    const user = userEvent.setup();
    renderFlow();

    await user.click(await screen.findByRole("radio", { name: /Crypto wallet/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("alert")).toHaveTextContent("To continue: pick the wallet's chain.");
    await user.click(screen.getByRole("radio", { name: /Solana/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(screen.getByLabelText("Wallet name (optional)"), "Cold");
    await user.click(screen.getByRole("button", { name: "Next" }));

    await user.click(await screen.findByRole("button", { name: "mock sign solana Cold" }));
    expect(await screen.findByText(/Wallet w9 verified/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add another" })).toBeInTheDocument();
    expect(mockApi.createAccount).not.toHaveBeenCalled();
  });

  it("on a phone, the wallet step says to finish on a computer", async () => {
    Object.defineProperty(window, "innerWidth", { value: 375, configurable: true, writable: true });
    const user = userEvent.setup();
    renderFlow("/add?what=wallet");

    await user.click(await screen.findByRole("radio", { name: /Ethereum/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/on a computer to finish this step/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mock sign/ })).not.toBeInTheDocument();
  });

  it("marks the current step for screen readers and lets you go back", async () => {
    const user = userEvent.setup();
    renderFlow("/add?what=loan");

    const steps = await screen.findByRole("navigation", { name: "Steps" });
    expect(steps.querySelector('[aria-current="step"]')).toHaveTextContent("Where");
    await user.click(screen.getByRole("button", { name: "What: done, go back to this step" }));
    expect(screen.getByRole("radio", { name: /Loan/ })).toBeChecked();
  });

  it("shows a load error", async () => {
    mockApi.platforms.mockRejectedValueOnce(new Error("boom"));
    renderFlow();
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
