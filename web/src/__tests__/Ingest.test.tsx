import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Ingest from "../routes/Ingest";
import { api } from "../lib/api";

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
    mockApi.accounts.mockResolvedValueOnce([
      { id: 1, name: "DBS Savings", platform: "DBS", account_type: "BANK", currency: "SGD", country: "SG" },
    ]);
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
      <MemoryRouter>
        <Ingest />
      </MemoryRouter>
    );

    await screen.findByText("Upload Statement CSV");
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
      <MemoryRouter>
        <Ingest />
      </MemoryRouter>
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
      <MemoryRouter>
        <Ingest />
      </MemoryRouter>
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
      <MemoryRouter>
        <Ingest />
      </MemoryRouter>
    );

    await screen.findByText("Recent Imports");
    const row = screen.getByText("ibkr.csv").closest("tr");
    expect(row).not.toBeNull();
    if (row) {
      await userEvent.click(row);
    }

    expect(await screen.findByText(/Job #99/)).toBeInTheDocument();
    const report = screen.getByText(/Status: IMPORTED/).closest(".card");
    expect(report).not.toBeNull();
    if (report) {
      const scoped = within(report);
      expect(scoped.getByText("Rows total: 2")).toBeInTheDocument();
    }
  });
});
