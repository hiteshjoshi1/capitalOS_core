# Issue 153: Fanout ingestion config API and UI

## Objective
- Expose the `152` fanout engine through supported backend APIs and a usable UI so compendium sources can be configured without direct database edits.
- Let users define deterministic logical-document fanout rules, metadata, author overrides, and optional parent-child linkage before ingestion.
- Make fanout ingestion previewable, auditable, and operable from the existing Author Ingestion workflow.

## Architecture Decisions
- Decision 1: Build on the `rag_sources.ingestion_config` JSONB field and the deterministic fanout/quality-gate engine added in issue 152 rather than inventing a second configuration system.
- Decision 2: Add backend API support to create/update source-level `ingestion_config` explicitly; users must not need direct SQL to use fanout.
- Decision 3: Extend the Author Ingestion UI with an advanced fanout-definition workflow rather than exposing raw JSON by default.
- Decision 4: Keep the basic single-URL ingestion flow simple. Fanout authoring should live behind explicit advanced controls and only appear when the user opts into compendium/omnibus handling.
- Decision 5: Support preview/validation of fanout definitions before or during ingestion, so users can see which logical documents will be created and what metadata each will carry.
- Decision 6: Surface ingestion outcomes per logical document in the UI, including created, rejected, skipped, and failed logical documents.
- Decision 7: The API must remain deterministic and schema-driven; no natural-language/LLM fanout authoring in this issue.

## Acceptance Criteria
- [ ] The backend exposes a supported API to set or update `ingestion_config` for a source without direct DB access.
- [ ] The backend API accepts deterministic fanout definitions including:
- [ ] ingestion mode
- [ ] logical-document keys/titles
- [ ] per-document selective rules
- [ ] author override
- [ ] publication year/date
- [ ] venue
- [ ] collection
- [ ] canonical metadata
- [ ] dedupe priority
- [ ] source section
- [ ] note taker
- [ ] work type
- [ ] optional parent linkage
- [ ] Existing simple ingestion requests continue to work unchanged without fanout configuration.
- [ ] The Author Ingestion UI provides an advanced fanout-definition workflow for compendium sources.
- [ ] The UI does not force raw JSON editing for the primary user path.
- [ ] The UI allows users to define multiple logical documents from one raw source.
- [ ] The UI supports per-document metadata entry and optional parent-child linkage.
- [ ] The UI supports author override for logical documents from a shared raw source.
- [ ] The UI surfaces validation errors clearly when the fanout definition is structurally invalid.
- [ ] The UI surfaces preview or validation output showing what logical documents will be created.
- [ ] The UI surfaces post-ingestion logical-document outcomes, including rejections from deterministic quality gates.
- [ ] The resulting workflow is testable end-to-end without direct DB edits.
- [ ] Backend and frontend tests cover API contracts, validation, preview/outcome rendering, and submission of fanout definitions.
- [ ] The feature is verifiable via Makefile commands and curl-verifiable requests.

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
- Last Updated: `2026-04-25`

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
  - `Should preview be a separate API endpoint or part of source update validation?`
  - `Should expert users also be allowed to paste raw JSON as an escape hatch?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
