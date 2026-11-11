// #399: Data Hub's backup line (U22), Settings facts (U24), the upload's grouped picker and
// pre-selection (U27).
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Account, BackupStatus, UploadDetect } from "../lib/api";
import { backupLine, relativeDayTime } from "../lib/backupStatus";
import { detectNote, groupAccounts } from "../lib/uploadAccount";

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
      registerIngestSignature: vi.fn(),
      removeIngestJob: vi.fn(),
      settingsFacts: vi.fn(),
      currencies: vi.fn(),
    },
  };
});

import { api } from "../lib/api";
import Ingest from "../routes/Ingest";
import SettingsFactsCard from "../components/SettingsFactsCard";

const mockApi = vi.mocked(api, true);

const NOW = new Date(2026, 10, 11, 14, 0); // 11 Nov 2026, 14:00 on this device

function status(over: Partial<BackupStatus> = {}): BackupStatus {
  return {
    available: true,
    last_verified_at: new Date(2026, 10, 11, 13, 0).toISOString(),
    age_hours: 1,
    stale: false,
    very_stale: false,
    next_run_at: new Date(2026, 10, 12, 13, 0).toISOString(),
    daily_time: "13:00",
    location: "icloud",
    location_label: "iCloud Drive",
    sets: 52,
    encrypted: true,
    last_run_at: new Date(2026, 10, 11, 13, 0).toISOString(),
    last_run_ok: true,
    status_written_at: null,
    ...over,
  };
}

describe("backup line (U22)", () => {
  it("says when, next and where", () => {
    const line = backupLine(status(), NOW);
    expect(line).toEqual({
      tone: "ok",
      text: "Last verified backup 13:00 today · next 13:00 tomorrow · iCloud Drive",
      detail: "52 kept, encrypted",
    });
  });

  it("is amber after two days and red after a failed run", () => {
    const old = backupLine(status({ last_verified_at: new Date(2026, 10, 8, 13, 0).toISOString(), stale: true }), NOW);
    expect(old?.tone).toBe("warn");
    expect(old?.text).toContain("Last verified backup 13:00 on 8 Nov");
    expect(old?.detail).toContain("make backup-now");
    const failed = backupLine(status({ stale: true, very_stale: true, last_run_ok: false }), NOW);
    expect(failed?.tone).toBe("bad");
    expect(failed?.detail).toContain("failed");
  });

  it("shows nothing where no backup reports", () => {
    expect(backupLine({ ...status(), available: false }, NOW)).toBeNull();
    expect(backupLine(null, NOW)).toBeNull();
  });

  it("names yesterday and another year", () => {
    expect(relativeDayTime(new Date(2026, 10, 10, 13, 5).toISOString(), NOW)).toBe("13:05 yesterday");
    expect(relativeDayTime(new Date(2025, 0, 2, 3, 0).toISOString(), NOW)).toBe("03:00 on 2 Jan 2025");
  });
});

const ACCOUNTS: Account[] = [
  { id: 1, name: "DBS Savings", platform: "DBS", account_type: "BANK", currency: "SGD" },
  { id: 2, name: "Citi Card", platform: "CITI", account_type: "CREDIT_CARD", currency: "SGD" },
  { id: 3, name: "UOB One", platform: "UOB", account_type: "BANK", currency: "SGD" },
  { id: 4, name: "Old UOB", platform: "UOB", account_type: "BANK", currency: "SGD", closed_on: "2026-01-31" },
  { id: 5, name: "IBKR", platform: "IBKR", account_type: "BROKER", currency: "USD" },
];

function detect(over: Partial<UploadDetect> = {}): UploadDetect {
  return {
    recognised: true,
    parser_key: "uob_account_xls_v1",
    file_label: "UOB bank-account statement",
    account_types: ["BANK"],
    candidate_account_ids: [3],
    suggested_account_id: 3,
    statement_last4: "1234",
    ...over,
  };
}

describe("account picker (U27)", () => {
  it("groups by kind, closed last", () => {
    expect(groupAccounts(ACCOUNTS).map((g) => [g.label, g.accounts.map((a) => a.id)])).toEqual([
      ["Bank accounts", [1, 3]],
      ["Credit cards", [2]],
      ["Brokers", [5]],
      ["Closed", [4]],
    ]);
  });

  it("explains what the file is and whether the chosen account fits", () => {
    expect(detectNote(detect(), ACCOUNTS, "3")).toBe("Looks like a UOB bank-account statement: matches UOB One.");
    expect(detectNote(detect(), ACCOUNTS, "1")).toBe("Looks like a UOB bank-account statement, which fits UOB One, not DBS Savings.");
    expect(detectNote(detect({ candidate_account_ids: [] }), ACCOUNTS, "")).toContain("none of your open accounts fits");
    expect(detectNote(detect({ recognised: false }), ACCOUNTS, "")).toContain("Format not recognised");
    expect(detectNote(null, ACCOUNTS, "")).toBeNull();
  });
});

describe("Ingest pre-selects from the file (U27)", () => {
  beforeEach(() => {
    mockApi.accounts.mockResolvedValue(ACCOUNTS);
    mockApi.ingestJobs.mockResolvedValue([]);
  });

  it("picks the one account that fits when none is chosen", async () => {
    mockApi.ingestDetect.mockResolvedValue(detect());
    render(
      <MemoryRouter>
        <Ingest />
      </MemoryRouter>,
    );
    await screen.findByText("Upload a statement");
    const file = new File(["x"], "UOB_ACC_TXN_History.xls");
    await userEvent.upload(screen.getByLabelText("Statement file"), file);
    await waitFor(() => expect((screen.getByLabelText("Account") as HTMLSelectElement).value).toBe("3"));
    expect(screen.getByTestId("ingest-detect").textContent).toBe("Looks like a UOB bank-account statement: matches UOB One.");
    expect(screen.getByRole("group", { name: "Bank accounts" })).toBeTruthy();
  });

  it("never changes an account already chosen", async () => {
    mockApi.ingestDetect.mockResolvedValue(detect());
    render(
      <MemoryRouter>
        <Ingest />
      </MemoryRouter>,
    );
    await screen.findByText("Upload a statement");
    await userEvent.selectOptions(screen.getByLabelText("Account"), "1");
    await userEvent.upload(screen.getByLabelText("Statement file"), new File(["x"], "UOB.xls"));
    await waitFor(() => expect(screen.getByTestId("ingest-detect").textContent).toContain("not DBS Savings"));
    expect((screen.getByLabelText("Account") as HTMLSelectElement).value).toBe("1");
  });
});

describe("Settings → How CapitalOS counts (U24)", () => {
  it("shows the month, the default cadence and the currency list", async () => {
    mockApi.settingsFacts.mockResolvedValue({ snapshot_day: 1, upload_stale_days: 30, base_currencies: ["SGD", "USD", "HKD", "INR"] });
    mockApi.currencies.mockResolvedValue([
      { code: "INR", name: "Indian Rupee" },
      { code: "SGD", name: "Singapore Dollar" },
      { code: "USD", name: "US Dollar" },
    ] as never);
    render(
      <MemoryRouter>
        <SettingsFactsCard />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/the calendar month/)).toBeTruthy();
    expect(screen.getByText(/due every 30 days/)).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/INR, SGD, USD\./)).toBeTruthy());
    expect(screen.getByRole("link", { name: /Accounts & sources/ }).getAttribute("href")).toBe("/operations/sources");
  });
});
