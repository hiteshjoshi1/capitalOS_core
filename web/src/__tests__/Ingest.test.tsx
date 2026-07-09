import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Ingest from "../routes/Ingest";
import { hasOrderedHeaderSubset, resolvePlatformParser } from "../routes/ingestUtils";
import { api } from "../lib/api";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", () => ({
  api: {
    accounts: vi.fn(),
    ingestJobs: vi.fn(),
    ingestJob: vi.fn(),
    ingestUpload: vi.fn(),
    registerIngestSignature: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

describe("Ingest helpers", () => {
  it("detects ordered header subsets", () => {
    expect(hasOrderedHeaderSubset("not-an-array", ["a"])).toBe(false);
    expect(
      hasOrderedHeaderSubset(
        ["transaction date", "Unnamed: 1", "transaction description", "withdrawal", "deposit", "available balance"],
        ["transaction date", "transaction description", "withdrawal", "deposit", "available balance"],
      ),
    ).toBe(true);
    expect(
      hasOrderedHeaderSubset(
        ["transaction date", "withdrawal", "deposit"],
        ["transaction date", "transaction description", "withdrawal", "deposit", "available balance"],
      ),
    ).toBe(false);
  });

  it("resolves parser from signature and platform labels", () => {
    expect(
      resolvePlatformParser(undefined, {
        file_kind: "excel",
        header: ["transaction date", "posting date", "description", "foreign currency type", "transaction amount(foreign)", "local currency type", "transaction amount(local)"],
      }),
    ).toEqual({ label: "Approve as UOB CC", parserKey: "uob_credit_card_xls_v1" });
    expect(
      resolvePlatformParser(undefined, {
        file_kind: "flat_csv",
        header: ["card transaction details for:", "dbs/posb mastercard platinum 5520-3800-5921-2403"],
      }),
    ).toEqual({ label: "Approve as DBS CC", parserKey: "dbs_credit_card_csv_v1" });
    expect(
      resolvePlatformParser("UOB Credit Card", undefined),
    ).toEqual({ label: "Approve as UOB CC", parserKey: "uob_credit_card_xls_v1" });
    expect(
      resolvePlatformParser("UOB One Account", undefined),
    ).toEqual({ label: "Approve as UOB", parserKey: "uob_account_xls_v1" });
    expect(
      resolvePlatformParser("IBKR", undefined),
    ).toEqual({ label: "Approve as IBKR", parserKey: "ibkr_activity_csv_v1" });
    expect(resolvePlatformParser(undefined, undefined)).toBeUndefined();
    expect(resolvePlatformParser("UNKNOWN", undefined)).toBeUndefined();
  });
});

describe("Ingest", () => {
  beforeEach(() => {
    mockApi.ingestJobs.mockResolvedValue([]);
  });

  it("uploads a file and shows report", async () => {
    const account = { id: 1, name: "Primary Savings", platform: "DBS", account_type: "BANK", currency: "SGD", country: "SG" };
    mockApi.accounts.mockResolvedValueOnce([account]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 10,
      status: "IMPORTED",
      platform: "DBS",
      account_id: 1,
      format_signature: "sig",
      counts: { rows_total: 1, transactions_parsed: 1, transactions_inserted: 1, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [{ ts: "2026-02-01T00:00:00Z", type: "INCOME", amount: 100, currency: "SGD" }],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([
      { id: 10, status: "IMPORTED", platform: "DBS", account_id: 1, original_filename: "dbs.csv", created_at: "2026-02-01T00:00:00Z" },
    ]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");

    expect(screen.getByRole("option", { name: `${account.name} (${account.currency})` })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Account"), "1");

    const file = new File(["data"], "dbs.csv", { type: "text/csv" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);

    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    expect(await screen.findByText(/job #10/i)).toBeInTheDocument();
    expect(screen.getByText("1 rows")).toBeInTheDocument();
    expect(screen.getByText("1 parsed")).toBeInTheDocument();
    expect(screen.getByText("1 inserted")).toBeInTheDocument();
  }, 15000);

  it("shows load error when initial fetch fails", async () => {
    mockApi.accounts.mockRejectedValueOnce(new Error("accounts failed"));
    mockApi.ingestJobs.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("Load error")).toBeInTheDocument();
    expect(screen.getByText("accounts failed")).toBeInTheDocument();
  });

  it("shows create-account call-to-action when accounts are empty", async () => {
    mockApi.accounts.mockResolvedValueOnce([]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(await screen.findByText("No accounts found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/accounts/new");
  });

  it("preselects the account from the alert account_id query parameter", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 21, name: "DBS Savings", platform: "DBS", account_type: "BANK", currency: "SGD", country: "SG" },
      { id: 22, name: "OCBC 360", platform: "OCBC", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter initialEntries={["/ingest?account_id=22"]}>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    const accountSelect = await screen.findByLabelText("Account");
    expect(accountSelect).toHaveValue("22");
  });

  it("surfaces string-based errors from upload, registration, and load-job paths", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 8, name: "Test", platform: "TEST", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([
      { id: 80, status: "NEEDS_MAPPING", platform: "TEST", account_id: 8, original_filename: "test.csv", created_at: null },
    ]);
    mockApi.ingestUpload.mockRejectedValueOnce("upload string failure");
    mockApi.ingestJob.mockRejectedValueOnce("job string failure");

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "8");
    const file = new File(["data"], "test.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("Statement file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));
    expect(await screen.findByText("upload string failure")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("row", { name: /80/i }));
    expect(await screen.findByText("job string failure")).toBeInTheDocument();
  });

  it("renders report fallbacks and warning/preview branches", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 9, name: "Parser Test", platform: "UOB", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: null,
      status: "NEEDS_MAPPING",
      platform: null,
      parser_key: null,
      format_signature: null,
      signature_debug: null,
      error_message: "format ambiguous",
      counts: {},
      section_summary: [],
      validation_warnings: ["row 3 ignored"],
      preview_transactions: [{ ts: null, type: null, amount: null, currency: null, category: null, merchant_counterparty: null }],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "9");
    const file = new File(["data"], "uob.xls", { type: "application/vnd.ms-excel" });
    await userEvent.upload(screen.getByLabelText("Statement file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    expect(await screen.findByText(/job #—/i)).toBeInTheDocument();
    expect(screen.getByText("format ambiguous")).toBeInTheDocument();
    expect(screen.getByText("row 3 ignored")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows approve button for Sharekhan mapping", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 2, name: "Sharekhan", platform: "SHAREKHAN", account_type: "BROKER", currency: "INR", country: "IN" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 11,
      status: "NEEDS_MAPPING",
      platform: "SHAREKHAN",
      account_id: 2,
      format_signature: "sig",
      counts: { rows_total: 0, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.registerIngestSignature.mockResolvedValueOnce({
      job_id: 11,
      status: "IMPORTED",
      platform: "SHAREKHAN",
      account_id: 2,
      counts: { rows_total: 1, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0, positions_parsed: 1, positions_inserted: 1 },
      section_summary: [],
      preview_transactions: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "2");

    const file = new File(["data"], "sharekhan.xls", { type: "application/vnd.ms-excel" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    const approve = await screen.findByRole("button", { name: "Approve as Sharekhan" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(11, "sharekhan_holdings_xls_v1");
    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("loads a job report from recent imports", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 7, name: "DBS", platform: "DBS", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([
      { id: 77, status: "IMPORTED", platform: "DBS", account_id: 7, original_filename: "dbs.csv", created_at: "2026-02-01T00:00:00Z" },
    ]);
    mockApi.ingestJob.mockResolvedValueOnce({
      job: {
        id: 77,
        status: "IMPORTED",
        platform: "DBS",
        account_id: 7,
        original_filename: "dbs.csv",
        stored_path: "data/dbs.csv",
        file_sha256: "x",
        format_signature: "sig",
        parser_key: "dbs_transaction_history_csv_v1",
        report_path: null,
        error_message: null,
        created_at: "2026-02-01T00:00:00Z",
        updated_at: "2026-02-01T00:00:00Z",
      },
      report: {
        job_id: 77,
        status: "IMPORTED",
        platform: "DBS",
        parser_key: "dbs_transaction_history_csv_v1",
        counts: { rows_total: 2, transactions_parsed: 2, transactions_inserted: 2, duplicates_skipped: 0 },
        section_summary: [],
        preview_transactions: [],
      },
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    const row = await screen.findByRole("row", { name: /77/i });
    await userEvent.click(row);

    expect(await screen.findByText(/job #77/i)).toBeInTheDocument();
    expect(mockApi.ingestJob).toHaveBeenCalledWith(77);
  });

  it("shows approve button for DBS Vickers mapping", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 3, name: "DBS Vickers", platform: "DBS_VICKERS", account_type: "BROKER", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 12,
      status: "NEEDS_MAPPING",
      platform: "DBS_VICKERS",
      account_id: 3,
      format_signature: "sig",
      counts: { rows_total: 0, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.registerIngestSignature.mockResolvedValueOnce({
      job_id: 12,
      status: "IMPORTED",
      platform: "DBS_VICKERS",
      account_id: 3,
      counts: { rows_total: 1, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0, positions_parsed: 1, positions_inserted: 1 },
      section_summary: [],
      preview_transactions: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "3");

    const file = new File(["data"], "dbs_vickers.xls", { type: "application/vnd.ms-excel" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    const approve = await screen.findByRole("button", { name: "Approve as DBS Vickers" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(12, "dbs_vickers_holdings_xls_v1");
    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("shows approve button for Citi CC mapping", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 4, name: "Citi", platform: "CITI", account_type: "CREDIT_CARD", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 13,
      status: "NEEDS_MAPPING",
      platform: "CITI",
      account_id: 4,
      format_signature: "sig",
      counts: { rows_total: 0, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.registerIngestSignature.mockResolvedValueOnce({
      job_id: 13,
      status: "IMPORTED",
      platform: "CITI",
      account_id: 4,
      counts: { rows_total: 51, transactions_parsed: 51, transactions_inserted: 51, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "4");

    const file = new File(["data"], "citi_credit_card_sample.csv", { type: "text/csv" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    const approve = await screen.findByRole("button", { name: "Approve as Citi CC" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(13, "citi_credit_card_csv_v1");
    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("shows approve button for UOB mapping when the account uses a legacy platform label", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 5, name: "UOB One", platform: "UOB One Account", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 14,
      status: "NEEDS_MAPPING",
      platform: "UOB One Account",
      account_id: 5,
      format_signature: "sig",
      counts: { rows_total: 0, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.registerIngestSignature.mockResolvedValueOnce({
      job_id: 14,
      status: "IMPORTED",
      platform: "UOB One Account",
      account_id: 5,
      counts: { rows_total: 3, transactions_parsed: 3, transactions_inserted: 3, duplicates_skipped: 0, positions_parsed: 1, positions_inserted: 1 },
      section_summary: [],
      preview_transactions: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "5");

    const file = new File(["data"], "uob_account.xls", { type: "application/vnd.ms-excel" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    const approve = await screen.findByRole("button", { name: "Approve as UOB" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(14, "uob_account_xls_v1");
    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("shows approve button for UOB mapping when the signature headers match even if platform is generic", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 6, name: "Savings", platform: "BANK", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 15,
      status: "NEEDS_MAPPING",
      platform: "BANK",
      account_id: 6,
      format_signature: "sig",
      signature_debug: {
        file_kind: "excel",
        header: [
          "transaction date",
          "transaction description",
          "withdrawal",
          "deposit",
          "available balance",
          "Unnamed: 5",
        ],
      },
      counts: { rows_total: 0, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.registerIngestSignature.mockResolvedValueOnce({
      job_id: 15,
      status: "IMPORTED",
      platform: "BANK",
      account_id: 6,
      counts: { rows_total: 3, transactions_parsed: 3, transactions_inserted: 3, duplicates_skipped: 0, positions_parsed: 1, positions_inserted: 1 },
      section_summary: [],
      preview_transactions: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "6");

    const file = new File(["data"], "uob_account.xls", { type: "application/vnd.ms-excel" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    const approve = await screen.findByRole("button", { name: "Approve as UOB" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(15, "uob_account_xls_v1");
    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("shows approve button for UOB CC mapping when the signature headers match a card statement", async () => {
    mockApi.accounts.mockResolvedValueOnce([
      { id: 16, name: "UOB Card", platform: "UOB", account_type: "CREDIT_CARD", currency: "SGD", country: "SG" },
    ]);
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.ingestUpload.mockResolvedValueOnce({
      job_id: 16,
      status: "NEEDS_MAPPING",
      platform: "UOB",
      account_id: 16,
      format_signature: "sig",
      signature_debug: {
        file_kind: "excel",
        header: [
          "transaction date",
          "posting date",
          "description",
          "foreign currency type",
          "transaction amount(foreign)",
          "local currency type",
          "transaction amount(local)",
          "Unnamed: 7",
        ],
      },
      counts: { rows_total: 0, transactions_parsed: 0, transactions_inserted: 0, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });
    mockApi.ingestJobs.mockResolvedValueOnce([]);
    mockApi.registerIngestSignature.mockResolvedValueOnce({
      job_id: 16,
      status: "IMPORTED",
      platform: "UOB",
      account_id: 16,
      parser_key: "uob_credit_card_xls_v1",
      counts: { rows_total: 11, transactions_parsed: 11, transactions_inserted: 11, duplicates_skipped: 0 },
      section_summary: [],
      preview_transactions: [],
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Upload Statement CSV");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "16");

    const file = new File(["data"], "uob_credit_card.xls", { type: "application/vnd.ms-excel" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);
    await userEvent.click(screen.getByRole("button", { name: "Upload statement" }));

    const approve = await screen.findByRole("button", { name: "Approve as UOB CC" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(16, "uob_credit_card_xls_v1");
    expect(await screen.findByText("Completed")).toBeInTheDocument();
  });

  it("loads report from recent imports", async () => {
    mockApi.accounts.mockResolvedValueOnce([]);
    mockApi.ingestJobs.mockResolvedValueOnce([
      { id: 99, status: "IMPORTED", platform: "IBKR", account_id: 3, original_filename: "ibkr.csv", created_at: "2026-02-01T00:00:00Z" },
    ]);
    mockApi.ingestJob.mockResolvedValueOnce({
      job: {
        id: 99,
        status: "IMPORTED",
        platform: "IBKR",
        account_id: 3,
        original_filename: "ibkr.csv",
        stored_path: "/data/raw/99/ibkr.csv",
        file_sha256: "sha",
        format_signature: "sig",
        parser_key: "ibkr_activity_csv_v1",
        report_path: "/data/reports/99.json",
        error_message: null,
        created_at: "2026-02-01T00:00:00Z",
        updated_at: "2026-02-01T00:00:00Z",
      },
      report: {
        job_id: 99,
        status: "IMPORTED",
        platform: "IBKR",
        account_id: 3,
        counts: { rows_total: 2, transactions_parsed: 2, transactions_inserted: 2, duplicates_skipped: 0 },
        section_summary: [],
        preview_transactions: [],
      },
    });

    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>
    );

    await screen.findByText("Recent Imports");
    const row = screen.getByText("ibkr.csv").closest('[role="row"]');
    expect(row).not.toBeNull();
    if (row) {
      await userEvent.click(row);
    }

    expect(await screen.findByText(/job #99/i)).toBeInTheDocument();
    const report = screen.getByText(/job #99/i).closest("section") as HTMLElement | null;
    expect(report).not.toBeNull();
    if (report) {
      const scoped = within(report);
      expect(scoped.getByText("2 rows")).toBeInTheDocument();
      expect(scoped.getByText("2 parsed")).toBeInTheDocument();
      expect(scoped.getByText("2 inserted")).toBeInTheDocument();
    }
  });
});
