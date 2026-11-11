// Uploads and import jobs: API calls (split out of lib/api.ts, #368).
import { UploadRefusedError, uploadRefusalFrom } from "../errors";
import { API_BASE, buildHeaders, formatHttpError, req } from "../http";
import type { ImportJobDetail, ImportJobListItem, ImportJobRemoval } from "../types/ingest";

export const ingestClient = {
  // asOf (YYYY-MM-DD): the statement's date, used when the file states none of its own (#141).
  // A refused upload throws UploadRefusedError (#180); allowAccountMismatch uploads a
  // statement that names another account anyway.
  ingestUpload: async (accountId: number, file: File, asOf?: string, opts?: { allowAccountMismatch?: boolean }) => {
    const form = new FormData();
    form.append("file", file);
    if (asOf) form.append("as_of", asOf);
    if (opts?.allowAccountMismatch) form.append("allow_account_mismatch", "true");
    const headers = buildHeaders(undefined, { includeJsonContentType: false });
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/ingest/upload?account_id=${accountId}`, {
        method: "POST",
        credentials: "include",
        headers,
        body: form,
      });
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`, { cause: err });
    }
    if (!res.ok) {
      const text = await res.text();
      const refusal = uploadRefusalFrom(res.status, text);
      if (refusal) throw new UploadRefusedError(refusal);
      throw new Error(formatHttpError(res.status, text));
    }
    return res.json() as Promise<Record<string, unknown>>;
  },
  ingestIbkr: async (accountId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const headers = buildHeaders(undefined, { includeJsonContentType: false });
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/ingest/ibkr?account_id=${accountId}`, {
        method: "POST",
        credentials: "include",
        headers,
        body: form,
      });
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(`Unable to reach API at ${API_BASE}: ${reason}`, { cause: err });
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(formatHttpError(res.status, text));
    }
    return res.json() as Promise<Record<string, unknown>>;
  },
  ingestJobs: () => req<ImportJobListItem[]>("/ingest/jobs"),
  ingestJob: (jobId: number) => req<ImportJobDetail>(`/ingest/jobs/${jobId}`),
  registerIngestSignature: (jobId: number, parserKey: string, asOf?: string) =>
    req<Record<string, unknown>>(`/ingest/jobs/${jobId}/register`, {
      method: "POST",
      body: JSON.stringify(asOf ? { parser_key: parserKey, as_of: asOf } : { parser_key: parserKey }),
    }),
  // "Remove this import" (#180): deletes the rows the upload wrote; the job stays as REMOVED.
  removeIngestJob: (jobId: number) =>
    req<ImportJobRemoval>(`/ingest/jobs/${jobId}/remove`, { method: "POST" }),
  ibkrFlexImportNow: (accountId: number, adminKey?: string) =>
    req<Record<string, unknown>>(`/portfolio/ibkr-flex/import-now?account_id=${encodeURIComponent(String(accountId))}`, {
      method: "POST",
      headers: adminKey ? { "X-Admin-Key": adminKey } : undefined,
    }),
};
