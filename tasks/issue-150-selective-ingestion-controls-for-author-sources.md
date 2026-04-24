# Issue 150: Selective ingestion controls for author sources

## Objective
- Allow users to ingest only relevant sections from long or mixed-content sources without manually preprocessing the document outside CapitalOS.
- Improve corpus purity and author-fidelity for omnibus HTML/text sources by adding deterministic section-selection controls to the ingestion workflow.
- Keep the default Author Ingestion UI simple, with advanced selective-ingestion controls hidden unless the user explicitly expands options.

## Architecture Decisions
- Decision 1: Support deterministic selective-ingestion controls in the backend ingestion request model for HTML/text sources: `start_after`, `stop_before`, `include_headings`, and `exclude_sections`.
- Decision 2: These controls are optional and hidden by default in the UI behind an explicit `+` / `Options` / `Advanced` affordance. The current simple URL-ingestion flow remains the default path.
- Decision 3: The first version should use document text structure and headings, not CSS selectors and not natural-language/LLM extraction rules.
- Decision 4: Selection behavior must be auditable and testable: the persisted ingestion record or job metadata should reflect which selective-ingestion options were applied.
- Decision 5: If a source does not contain the requested headings/sections, the backend must fail clearly or report zero selected content rather than silently ingesting the full source.

## Acceptance Criteria
- [ ] The author-ingestion backend accepts optional selective-ingestion fields: `start_after`, `stop_before`, `include_headings`, and `exclude_sections`.
- [ ] These fields are optional; existing ingestion requests without them continue to work unchanged.
- [ ] The Author Ingestion UI keeps today’s basic controls visible by default and does not force users to see or fill selective-ingestion fields.
- [ ] The selective-ingestion controls are shown only after the user clicks an explicit advanced/options affordance.
- [ ] `start_after` causes ingestion to begin only after the first matching heading/section marker.
- [ ] `stop_before` causes ingestion to stop before the first matching heading/section marker.
- [ ] `include_headings` limits ingestion to matching headings/sections only.
- [ ] `exclude_sections` removes matching headings/sections from the final ingested content.
- [ ] The controls work deterministically for HTML/text sources and do not rely on LLM interpretation.
- [ ] If no matching content remains after applying the rules, the ingestion job fails clearly or returns a structured no-content-selected result; it must not silently ingest the full source.
- [ ] The applied selective-ingestion rules are stored in source/job/document metadata so later debugging and review can explain what was actually ingested.
- [ ] The UI surfaces validation errors or backend failures clearly when selective-ingestion rules do not match the source.
- [ ] The resulting ingested content for a mixed source reflects only the selected sections, improving author fidelity and retrieval quality.
- [ ] Tests cover backend rule application, failure/no-match handling, metadata persistence, and frontend advanced-controls behavior.
- [ ] The feature is verifiable via Makefile commands and a curl-verifiable ingestion request.

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
- Last Updated: `2026-04-24`

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
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
