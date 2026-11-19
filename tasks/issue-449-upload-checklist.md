# Issue 449: Monthly upload checklist + one drop zone for many files (V23 from #432)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/449

## Objective
- The monthly upload routine gets one place: what's still to upload this month, and one drop of
  all the files, each routed to its account.

## Architecture Decisions
- **Checklist (`app/services/upload_checklist.py`, `GET /ingest/checklist`).** Sources are the
  upload kinds from source freshness (#252: broker, bank, card, other statements; not Flex, wallets,
  quote/FX feeds; not a source set to `off`). A source is *done* for the calendar month (app
  timezone) once an IMPORTED, not removed, import for it was created this month, or it has data
  dated this month. The import counts because October's statement uploaded in November has
  October-dated data. Rejected: "on time" from freshness, since that's on time for weeks after an
  upload and doesn't say what's left this month.
- **Inbox:** `monthly_uploads`, low, "This month's uploads: N of M", detail lists what's missing;
  when all are done, an all-good line instead. Built from the same function, so the page and the
  Inbox agree.
- **Many files:** the drop zone takes several files. Each one is detected (`POST /ingest/detect`,
  nothing stored) and goes to the one account it fits. A file that fits several accounts, or none,
  asks for one. "Upload N files" sends them one after another (imports lock per account). Each row
  then says what it did (rows added, duplicates, holdings, the upload's effect line from U28). A
  refusal offers "Upload anyway" when the server allows it; an unknown format links to the job.
  One file keeps the existing single form. No backend change for this part.

## Acceptance Criteria
- [x] (a) Inbox item "This month's uploads: N of M" listing what's missing.
- [x] (b) One drop zone for many files, routed by detection, asking only when unsure.
- [x] (c) A short per-file summary after the batch, plus a batch line ("3 imported, 1 not imported").
- [x] The Upload page shows the checklist with an Upload link per missing source.

## How To Test
- Backend: `tests/test_upload_checklist.py` (done rules, kinds left out, scoping, Inbox item).
- Frontend: `src/__tests__/batchUpload449.test.tsx` (helpers, checklist card, batch flow with a
  pick, a refusal and "Upload anyway", one file keeps the single form).
- On the test instance: Data Hub → Inbox shows "This month's uploads"; Upload page shows the
  checklist; drop several statements at once.

<!-- IMMUTABLE_PLAN_END -->
