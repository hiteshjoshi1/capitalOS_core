# Issue 157: Nick Sleep corpus remediation and letter-level re-ingestion

## Objective
- Replace the current Nick Sleep omnibus-style corpus representation with a cleaner letter-level corpus so the author library and retrieval system operate on individual writings instead of one giant blob.
- Preserve provenance and metadata while making Nick Sleep’s corpus structurally consistent with the document-first library model used for Buffett letters and Munger talks/interviews.

## Architecture Decisions
- Decision 1: This is a corpus remediation and re-ingestion issue, not a reader/UI issue.
- Decision 2: Nick Sleep content should be represented as individual letters or logical writings wherever the source material supports it.
- Decision 3: If the current source is an omnibus document, it should be deleted from the active Nick Sleep corpus after replacement or otherwise marked obsolete so it does not dominate the library/retrieval experience.
- Decision 4: The remediation path should use the generic ingestion and fanout machinery introduced in issues 152 and 153; it must not hardcode Nick Sleep-specific runtime logic in code.
- Decision 5: Each resulting Nick Sleep logical document should carry document-level metadata such as title, year/date, collection, work type, canonical status, and provenance URL.
- Decision 6: Validation should confirm that each resulting logical document contains real body text and not only headings or table-of-contents fragments before final insertion.

## Acceptance Criteria
- [ ] The current Nick Sleep omnibus representation is identified and remediated.
- [ ] Nick Sleep’s corpus is re-ingested as individual letters or equivalent logical writings rather than one giant omnibus blob.
- [ ] Each resulting Nick Sleep document has document-level `author_id = nick_sleep`.
- [ ] Each resulting Nick Sleep document has clean metadata including at least title, date/year when available, source URL, and work classification.
- [ ] The old omnibus representation no longer dominates the author library or retrieval experience.
- [ ] Validation artifacts or equivalent evidence confirm that the new logical documents contain real body text.
- [ ] The remediation uses generic ingestion/fanout capabilities rather than Nick Sleep-specific hardcoded runtime logic.
- [ ] The final result is compatible with the author library grouping model in issue 154.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not_started`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-26`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `<command or decision>`
- Open questions:
  - `What is the best canonical source set for letter-level Nick Sleep ingestion?`
  - `Should any omnibus source be retained only as audit/fallback provenance after letter-level re-ingestion?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

