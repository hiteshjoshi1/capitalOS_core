# Issue 158: AI Sage result context, full document reader, and original source toggle

## Objective
- Improve AI Sage result usability so a user can move from a ranked passage snippet to trustworthy surrounding context, the full logical document, and the original source when needed.
- Reuse the existing Author Library reader instead of introducing a second document-reading stack.
- Support source fallback when parsed text formatting is weak, especially for PDFs, without making remote-source viewing the default experience.

## Architecture Decisions
- Decision 1: AI Sage result reading should remain document-first. The default path is ranked passage -> adjacent context -> Author Library logical document reader.
- Decision 2: Every ranked corpus result should carry stable linkage back to stored corpus entities such as `document_id`, `chunk_id`, and enough metadata to support reader navigation.
- Decision 3: Adjacent-context expansion should be generic across authors and corpus classes, not implemented as author-specific special cases.
- Decision 4: The dedicated reader surface should continue to use stored logical-document text by default, because the ingested corpus remains the primary readable artifact.
- Decision 5: The reader should also support an optional `View original source` mode for cases where users want to inspect original PDF/HTML formatting or verify fidelity against the upstream source.
- Decision 6: Original-source viewing should be lazy and opt-in:
- Decision 6a: no source embed/download should happen by default when the reader opens
- Decision 6b: the user explicitly toggles into original-source mode
- Decision 6c: if inline embed is not possible, the system should degrade to `Open source` rather than failing silently
- Decision 7: The first version should prefer remote source URLs for original-source viewing rather than introducing immediate source-artifact storage requirements.
- Decision 8: The design should remain compatible with future source-artifact storage if remote URLs prove unstable or embeddability is poor.
- Decision 9: The feature should build on the existing Author Library document reader and route structure from issue 154 rather than inventing a separate AI Sage-only reader.
- Decision 10: This issue is about result-context and reading UX, not retrieval-ranking quality itself.

## Acceptance Criteria
- [ ] Every ranked corpus result in AI Sage exposes stable document linkage sufficient to open the relevant logical document.
- [ ] Every ranked corpus result can expose adjacent context from the same logical document.
- [ ] A user can move from an AI Sage result card into the Author Library reader for the relevant logical document.
- [ ] When feasible, the reader can land near the relevant chunk or otherwise highlight/anchor the relevant passage area.
- [ ] The flow is generic across current and future authors and corpus types.
- [ ] No author-specific hardcoding is introduced.
- [ ] Existing AI Sage and Author Library behavior remains backward-compatible.
- [ ] The reader supports an opt-in original-source view for documents whose source URL is available.
- [ ] Original-source view supports PDFs when the remote source is embeddable.
- [ ] Original-source view supports graceful fallback when embedding is not possible, such as opening the remote source in a new tab/window.
- [ ] The parsed logical-document reader remains the default reading surface; original-source view is secondary and user-triggered.
- [ ] No remote source is loaded automatically merely by opening the reader.
- [ ] The implementation is compatible with future local source-artifact storage but does not require artifact storage in the first version.
- [ ] Tests cover result linkage, adjacent-context expansion behavior, reader navigation, and original-source toggle/fallback behavior.
- [ ] The feature is verifiable via Makefile commands and curl-verifiable APIs where applicable.

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
- Last Updated: `2026-04-28`

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
  - `Should first-version original-source viewing support only PDFs, or also HTML source rendering when source_type=html?`
  - `Should passage anchoring prefer scroll-to-chunk, text highlight, or both when chunk-level offsets are available?`
  - `If a source URL is dead or blocked from embedding, should the UI show a retry/open-source fallback banner or silently hide original-source mode?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
