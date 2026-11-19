// #449 (V23): this month's upload checklist, and several statements dropped at once.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Ingest from "../routes/Ingest";
import { api, UploadRefusedError } from "../lib/api";
import type { Account, UploadDetect } from "../lib/api";
import { batchSummary, checklistMeta, newRow, phaseOf, rowNote, uploadable, withDetect } from "../lib/batchUpload";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    UploadRefusedError: actual.UploadRefusedError,
    api: {
      accounts: vi.fn(),
      ingestJobs: vi.fn(),
      ingestJob: vi.fn(),
      ingestUpload: vi.fn(),
      ingestDetect: vi.fn(),
      ingestChecklist: vi.fn(),
      registerIngestSignature: vi.fn(),
      removeIngestJob: vi.fn(),
    },
  };
});
const mockApi = vi.mocked(api, true);

const acct = (id: number, name: string, account_type: string, platform: string): Account =>
  ({ id, name, platform, account_type, currency: "SGD", country: "SG" }) as Account;
const BANK = acct(1, "DBS Savings", "BANK", "DBS");
const CARD_A = acct(2, "UOB Card", "CREDIT_CARD", "UOB");
const CARD_B = acct(3, "UOB Card 2", "CREDIT_CARD", "UOB");
const ACCOUNTS = [BANK, CARD_A, CARD_B];

const detect = (candidates: number[], suggested: number | null, label = "DBS account statement"): UploadDetect => ({
  recognised: true,
  parser_key: "x",
  file_label: label,
  account_types: [],
  candidate_account_ids: candidates,
  suggested_account_id: suggested,
  statement_last4: null,
});
const file = (name: string) => new File(["data"], name, { type: "text/csv" });

describe("batch helpers", () => {
  it("routes a file to the one account it fits, and never overrides a pick", () => {
    const row = newRow(file("2026_10_31.xls"), 0, "2026-11-19");
    expect(row.asOf).toBe("2026-10-31");
    expect(withDetect(row, detect([1], 1), ACCOUNTS).accountId).toBe("1");
    expect(withDetect({ ...row, accountId: "2" }, detect([1], 1), ACCOUNTS).accountId).toBe("2");
    const unsure = withDetect(row, detect([2, 3], null, "UOB card statement"), ACCOUNTS);
    expect(unsure.accountId).toBe("");
    expect(rowNote(unsure, ACCOUNTS)).toBe("UOB card statement: fits UOB Card or UOB Card 2. Pick one.");
    expect(uploadable([unsure])).toEqual([]);
    expect(rowNote(withDetect(row, null, ACCOUNTS), ACCOUNTS)).toBe("Format not recognised: pick the account.");
  });

  it("says what each upload did, and sums the batch up", () => {
    const base = withDetect(newRow(file("a.csv"), 0), detect([1], 1), ACCOUNTS);
    expect(phaseOf({ status: "IMPORTED" })).toBe("imported");
    expect(phaseOf({ status: "NEEDS_MAPPING" })).toBe("needs_mapping");
    expect(phaseOf({ status: "FAILED" })).toBe("failed");
    const done = { ...base, phase: "imported" as const, report: { counts: { transactions_inserted: 12, duplicates_skipped: 3 } } };
    expect(rowNote(done, ACCOUNTS)).toBe("Imported into DBS Savings: 12 transactions added, 3 already there");
    const holdings = { ...base, phase: "imported" as const, report: { counts: { positions_parsed: 4, canonical_positions_written: 4 } } };
    expect(rowNote(holdings, ACCOUNTS)).toBe("Imported into DBS Savings: 4 holdings saved");
    expect(batchSummary([done, holdings, { ...base, phase: "refused" }, { ...base, accountId: "", phase: "ready" }])).toBe(
      "2 imported, 1 not imported, 1 waiting for an account",
    );
    expect(checklistMeta("2026-11-03", "2026-10-31")).toMatch(/^Last upload 3 Nov/);
    expect(checklistMeta(null, "2026-08-29")).toMatch(/^Last data 29 Aug/);
    expect(checklistMeta(null, null)).toBe("No data yet");
    expect(checklistMeta("2026-10-31", "2026-11-06")).toMatch(/^Last data 6 Nov/); // ticked by newer data
  });
});

describe("Upload page (#449)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.accounts.mockResolvedValue(ACCOUNTS);
    mockApi.ingestJobs.mockResolvedValue([]);
    mockApi.ingestChecklist.mockResolvedValue({
      month: "2026-11",
      done: 1,
      total: 2,
      sources: [
        { source_key: "account:2", account_id: 2, label: "UOB Card", platform: "UOB", kind: "card_statement", done: false,
          last_import_date: null, last_data_date: "2026-08-29", overdue: true },
        { source_key: "account:1", account_id: 1, label: "DBS Savings", platform: "DBS", kind: "bank_statement", done: true,
          last_import_date: "2026-11-03", last_data_date: "2026-10-31", overdue: false },
      ],
    });
  });

  const renderPage = () =>
    render(
      <ThemeProvider>
        <MemoryRouter>
          <Ingest />
        </MemoryRouter>
      </ThemeProvider>,
    );

  it("shows this month's checklist with an Upload link for what's missing", async () => {
    renderPage();
    const card = await screen.findByLabelText("This month's uploads");
    expect(within(card).getByText(/uploads · 1 of 2/)).toBeInTheDocument();
    const rows = within(card).getAllByTestId("checklist-row");
    expect(rows[0]).toHaveTextContent("UOB Card");
    expect(rows[0]).toHaveTextContent("overdue");
    expect(within(rows[0]).getByRole("link", { name: "Upload" })).toHaveAttribute("href", "/ingest?account_id=2");
    expect(within(rows[1]).queryByRole("link")).toBeNull(); // the done one, folded under "1 done"
    expect(within(card).getByText("1 done")).toBeInTheDocument();
  });

  it("still works when the checklist can't load", async () => {
    mockApi.ingestChecklist.mockRejectedValue(new Error("boom"));
    renderPage();
    await screen.findByText("Upload a statement");
    expect(screen.queryByLabelText("This month's uploads")).toBeNull();
  });

  it("routes several files, asks only for the unsure one, uploads all and sums up", async () => {
    mockApi.ingestDetect.mockImplementation(async (f: File) =>
      f.name.startsWith("dbs") ? detect([1], 1) : detect([2, 3], null, "UOB card statement"),
    );
    mockApi.ingestUpload
      .mockResolvedValueOnce({ job_id: 1, status: "IMPORTED", counts: { transactions_inserted: 5 } })
      .mockRejectedValueOnce(
        new UploadRefusedError({ code: "account_mismatch", message: "This statement names another card.", override_field: "allow_account_mismatch" } as never),
      )
      .mockResolvedValueOnce({ job_id: 3, status: "IMPORTED", counts: { transactions_inserted: 2 } });
    renderPage();
    await screen.findByText("Upload a statement");
    await userEvent.upload(screen.getByLabelText("Statement file"), [file("dbs.csv"), file("uob.xls")]);

    const batch = await screen.findByLabelText("Upload several statements");
    await waitFor(() => expect(within(batch).getByRole("button", { name: "Upload 1 file" })).toBeEnabled());
    expect(within(batch).getAllByTestId("batch-row")[1]).toHaveTextContent("Pick one.");

    await userEvent.selectOptions(within(batch).getByLabelText("Account for uob.xls"), "2");
    await userEvent.click(within(batch).getByRole("button", { name: "Upload 2 files" }));

    await waitFor(() => expect(within(batch).getByTestId("batch-summary")).toHaveTextContent("1 imported, 1 not imported"));
    // One after another, each to its own account.
    expect(mockApi.ingestUpload.mock.calls.map((c) => [c[0], (c[1] as File).name])).toEqual([[1, "dbs.csv"], [2, "uob.xls"]]);
    const rows = within(batch).getAllByTestId("batch-row");
    expect(rows[0]).toHaveTextContent("Imported into DBS Savings: 5 transactions added");
    expect(rows[1]).toHaveTextContent("Not imported: This statement names another card.");

    await userEvent.click(within(rows[1]).getByRole("button", { name: "Upload anyway" }));
    await waitFor(() => expect(within(batch).getByTestId("batch-summary")).toHaveTextContent("2 imported"));
    expect(mockApi.ingestUpload.mock.calls[2][3]).toEqual({ allowAccountMismatch: true });
    expect(mockApi.ingestChecklist.mock.calls.length).toBeGreaterThanOrEqual(3); // refreshed after each run
  }, 20000);

  it("one file keeps the single-upload form", async () => {
    renderPage();
    await screen.findByText("Upload a statement");
    await userEvent.upload(screen.getByLabelText("Statement file"), file("dbs.csv"));
    expect(screen.queryByLabelText("Upload several statements")).toBeNull();
    expect(screen.getByText("dbs.csv")).toBeInTheDocument();
  });
});
