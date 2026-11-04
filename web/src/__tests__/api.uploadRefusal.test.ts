import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// #180: a refused upload (409 with a structured detail) becomes UploadRefusedError,
// the override is sent as a form field, and removal posts to the job.
describe("upload refusals and removal", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("throws UploadRefusedError carrying the refusal", async () => {
    const detail = {
      code: "statement_account_mismatch",
      message: "This statement is for the account ending 4321.",
      job_id: 3,
      override_field: "allow_account_mismatch",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: () => Promise.resolve({ detail }),
        text: () => Promise.resolve(JSON.stringify({ detail })),
      }),
    );
    const { api, UploadRefusedError } = await import("../lib/api");

    const error = await api.ingestUpload(1, new File(["x"], "s.csv")).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(UploadRefusedError);
    expect((error as InstanceType<typeof UploadRefusedError>).refusal).toEqual(detail);
    expect((error as Error).message).toBe(detail.message);
  });

  it("sends the override and posts removals", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve("{}"),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const { api } = await import("../lib/api");

    await api.ingestUpload(1, new File(["x"], "s.csv"), "2026-02-19", { allowAccountMismatch: true });
    const form = fetchSpy.mock.calls[0][1].body as FormData;
    expect(form.get("allow_account_mismatch")).toBe("true");
    expect(form.get("as_of")).toBe("2026-02-19");

    await api.ingestUpload(1, new File(["x"], "s.csv"));
    expect((fetchSpy.mock.calls[1][1].body as FormData).get("allow_account_mismatch")).toBeNull();

    await api.removeIngestJob(9);
    expect(String(fetchSpy.mock.calls[2][0])).toContain("/ingest/jobs/9/remove");
    expect(fetchSpy.mock.calls[2][1].method).toBe("POST");
  });

  it("shows a structured detail's message for other requests", async () => {
    const detail = { code: "account_type_mismatch", message: "Belongs to a bank account (BANK)." };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: () => Promise.resolve({ detail }),
        text: () => Promise.resolve(JSON.stringify({ detail })),
      }),
    );
    const { api } = await import("../lib/api");

    await expect(api.registerIngestSignature(3, "dbs_transaction_history_csv_v1")).rejects.toThrow(
      "Belongs to a bank account (BANK).",
    );
  });
});
