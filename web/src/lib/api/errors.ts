// Upload refusals (#180) (split out of lib/api.ts, #368).
import type { UploadRefusal } from "./types/ingest";

export class UploadRefusedError extends Error {
  refusal: UploadRefusal;

  constructor(refusal: UploadRefusal) {
    super(refusal.message);
    this.name = "UploadRefusedError";
    this.refusal = refusal;
  }
}

export function uploadRefusalFrom(status: number, rawText: string): UploadRefusal | null {
  if (status !== 409) return null;
  try {
    const detail = (JSON.parse(rawText) as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const refusal = detail as UploadRefusal;
      if (typeof refusal.code === "string" && typeof refusal.message === "string") return refusal;
    }
  } catch {
    // Not JSON.
  }
  return null;
}
