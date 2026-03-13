import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Ingest from "../routes/Ingest";
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
    const nav = screen.getByRole("navigation", { name: "Primary navigation" });
    expect(within(nav).getAllByRole("link")).toHaveLength(1);
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(within(nav).queryByRole("link", { name: "Ingest" })).not.toBeInTheDocument();

    expect(screen.getByRole("option", { name: `${account.name} (${account.currency})` })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Account"), "1");

    const file = new File(["data"], "dbs.csv", { type: "text/csv" });
    const input = screen.getByLabelText("Statement file") as HTMLInputElement;
    await userEvent.upload(input, file);

    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    expect(await screen.findByText(/Job #10/)).toBeInTheDocument();
    expect(screen.getByText(/Status: IMPORTED/)).toBeInTheDocument();
    expect(screen.getByText("Rows total: 1")).toBeInTheDocument();
    expect(screen.getByText("Parsed: 1")).toBeInTheDocument();
    expect(screen.getByText("Inserted: 1")).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    const approve = await screen.findByRole("button", { name: "Approve as Sharekhan" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(11, "sharekhan_holdings_xls_v1");
    expect(await screen.findByText(/Status: IMPORTED/)).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    const approve = await screen.findByRole("button", { name: "Approve as DBS Vickers" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(12, "dbs_vickers_holdings_xls_v1");
    expect(await screen.findByText(/Status: IMPORTED/)).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    const approve = await screen.findByRole("button", { name: "Approve as Citi CC" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(13, "citi_credit_card_csv_v1");
    expect(await screen.findByText(/Status: IMPORTED/)).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    const approve = await screen.findByRole("button", { name: "Approve as UOB" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(14, "uob_account_xls_v1");
    expect(await screen.findByText(/Status: IMPORTED/)).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    const approve = await screen.findByRole("button", { name: "Approve as UOB" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(15, "uob_account_xls_v1");
    expect(await screen.findByText(/Status: IMPORTED/)).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Upload CSV" }));

    const approve = await screen.findByRole("button", { name: "Approve as UOB CC" });
    await userEvent.click(approve);

    expect(mockApi.registerIngestSignature).toHaveBeenCalledWith(16, "uob_credit_card_xls_v1");
    expect(await screen.findByText(/Status: IMPORTED/)).toBeInTheDocument();
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
    const row = screen.getByText("ibkr.csv").closest("tr");
    expect(row).not.toBeNull();
    if (row) {
      await userEvent.click(row);
    }

    expect(await screen.findByText(/Job #99/)).toBeInTheDocument();
    const report = screen.getByText(/Status: IMPORTED/).closest(".card") as HTMLElement | null;
    expect(report).not.toBeNull();
    if (report) {
      const scoped = within(report);
      expect(scoped.getByText("Rows total: 2")).toBeInTheDocument();
    }
  });
});
