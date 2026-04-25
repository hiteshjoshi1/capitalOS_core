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
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `completed`
- Workflow Status: `completed`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-25`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` — `make lint`
- `typecheck`: `pass` — `make typecheck`
- `tests`: `pass` — `make contract-backend && make test-backend && make contract-frontend && make test-frontend && make orch-test`
- `e2e`: `pass` — `make e2e`
- `api-smoke`: `pass` — `make api-smoke`
- `policy-checks`: `pass` — `make api-rebuild && make openapi`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `openapi.json` — reason: refreshed API schema snapshot after adding fanout preview/config endpoints

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Run the independent pipeline verification for issue 153.`
- Open questions:
  - `None`
- If PR raised but intent partial:
  - unmet criteria: `None`
  - follow-up issue: `None`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented the fanout ingestion config feature end to end: the backend now supports source-level ingestion_config updates plus deterministic preview, and Author Ingestion now has an opt-in compendium workflow that authors fanout rules without raw JSON and renders per-logical-document outcomes.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Backend source APIs support creating, previewing, and updating deterministic fanout ingestion_config without direct database edits.
- Acceptance criterion: Fanout definitions support multiple logical documents, per-document selective rules, author overrides, metadata fields, dedupe priority, source section, work type, note taker, and parent linkage.
- Acceptance criterion: The simple single-URL ingestion path remains available when fanout is not enabled.
- Acceptance criterion: Author Ingestion provides an opt-in advanced compendium workflow that avoids raw JSON editing in the primary path.
- Acceptance criterion: The UI previews logical documents, surfaces validation failures, and shows per-logical-document ingestion outcomes including deterministic rejections.
- Acceptance criterion: Backend and frontend tests cover fanout API contracts, preview, submission, and outcome rendering, and the workflow is verifiable through Makefile commands.

## Prepare
Checked out `feature/issue-153-fanout-ingestion-config-api-and-ui` from `main` and ensured task file exists.

## Plan Summary
1) Add validated backend APIs around rag_sources.ingestion_config, including explicit source updates and fanout preview. 2) Extend the Author Ingestion client and UI with an advanced, opt-in compendium workflow for multi-document fanout authoring. 3) Surface logical-document ingestion outcomes in the UI. 4) Refresh OpenAPI and run the full required Makefile verification sequence.

### Architecture Decisions
- Kept rag_sources.ingestion_config as the single persisted configuration surface and layered explicit API support on top of it instead of introducing a second config store.
- Added a dedicated schema-driven preview endpoint that reuses the deterministic fanout model and validates duplicate keys, parent references, and author overrides before ingestion.
- Kept the basic URL ingestion path unchanged by hiding fanout authoring behind an explicit compendium toggle in Author Ingestion.
- Used the existing job.stats_json.documents outcomes from the ingestion pipeline to render created and rejected logical-document results in the UI.

### Acceptance Criteria
- Backend source APIs support creating, previewing, and updating deterministic fanout ingestion_config without direct database edits.
- Fanout definitions support multiple logical documents, per-document selective rules, author overrides, metadata fields, dedupe priority, source section, work type, note taker, and parent linkage.
- The simple single-URL ingestion path remains available when fanout is not enabled.
- Author Ingestion provides an opt-in advanced compendium workflow that avoids raw JSON editing in the primary path.
- The UI previews logical documents, surfaces validation failures, and shows per-logical-document ingestion outcomes including deterministic rejections.
- Backend and frontend tests cover fanout API contracts, preview, submission, and outcome rendering, and the workflow is verifiable through Makefile commands.

### Planned Paths
- `api/app/routers/rag.py`
- `api/app/rag/ingestion`
- `api/tests`
- `web/src/routes/AuthorIngestion.tsx`
- `web/src/lib/api.ts`
- `web/src/__tests__/AuthorIngestion.test.tsx`
- `openapi.json`
- `tasks/issue-153-fanout-ingestion-config-api-and-ui.md`

## Build Summary
Implemented the fanout ingestion config feature end to end: the backend now supports source-level ingestion_config updates plus deterministic preview, and Author Ingestion now has an opt-in compendium workflow that authors fanout rules without raw JSON and renders per-logical-document outcomes.

### Changed Files
- `api/app/rag/ingestion/events.py`
- `api/app/rag/ingestion/fanout.py`
- `api/app/routers/rag.py`
- `api/tests/test_rag_author_ingestion_ui.py`
- `openapi.json`
- `tasks/issue-153-fanout-ingestion-config-api-and-ui.md`
- `web/src/__tests__/AuthorIngestion.test.tsx`
- `web/src/lib/api.ts`
- `web/src/routes/AuthorIngestion.tsx`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented the fanout ingestion config feature end to end: the backend now supports source-level ingestion_config updates plus deterministic preview, and Author Ingestion now has an opt-in compendium workflow that authors fanout rules without raw JSON and renders per-logical-document outcomes.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` The backend exposes a supported API to set or update ingestion_config for a source without direct DB access.: api/app/routers/rag.py adds PATCH /rag/sources/{source_id}/ingestion-config and extends source registration/ingest flows to persist ingestion_config; api/tests/test_rag_author_ingestion_ui.py covers patching and ingest submission.
- `pass` The backend API accepts deterministic fanout definitions including mode, logical-document fields, selective rules, metadata, author override, and optional parent linkage.: api/app/routers/rag.py adds IngestionConfigIn and LogicalDocumentConfigIn for mode, keys, titles, selective_ingestion, author_id, publication metadata, venue, collection, canonical fields, dedupe_priority, source_section, note_taker, work_type, metadata, and parent_key.
- `pass` Existing simple ingestion requests continue to work unchanged without fanout configuration.: api/app/rag/ingestion/fanout.py preserves the single_work path when no fanout config is supplied, and api/tests/test_rag_fanout.py keeps the single-work regression coverage passing.
- `pass` The Author Ingestion UI provides an advanced fanout-definition workflow for compendium sources.: web/src/routes/AuthorIngestion.tsx adds the opt-in compendium/fanout editor with multiple logical-document cards and preview controls.
- `pass` The UI does not force raw JSON editing for the primary user path and supports multiple logical documents, per-document metadata, parent linkage, and author override.: web/src/routes/AuthorIngestion.tsx uses form controls, author selects, parent selectors, and key/value metadata rows instead of a raw JSON textarea; web/src/__tests__/AuthorIngestion.test.tsx covers preview and submission through the form.
- `pass` The UI surfaces validation errors clearly when the fanout definition is structurally invalid.: web/src/routes/AuthorIngestion.tsx renders fanoutPreviewError and ingestError banners; web/src/__tests__/AuthorIngestion.test.tsx verifies backend preview failures are shown to the user.
- `pass` The UI surfaces preview or validation output showing what logical documents will be created.: web/src/routes/AuthorIngestion.tsx renders a preview table from POST /rag/fanout/preview; api/tests/test_rag_author_ingestion_ui.py and web/src/__tests__/AuthorIngestion.test.tsx cover preview payloads and rendering.
- `pass` The UI surfaces post-ingestion logical-document outcomes, including rejections from deterministic quality gates.: web/src/routes/AuthorIngestion.tsx parses job.stats_json.documents and renders created/rejected outcome details; web/src/__tests__/AuthorIngestion.test.tsx verifies rejected outcomes render with failure_category.
- `pass` Backend and frontend tests cover API contracts, validation, preview/outcome rendering, and submission of fanout definitions.: api/tests/test_rag_author_ingestion_ui.py adds backend preview/update/submission tests, web/src/__tests__/AuthorIngestion.test.tsx adds UI preview/validation/submission/outcome tests, and the full backend/frontend suites passed.
- `pass` The feature is verifiable via Makefile commands and curl-verifiable requests.: make api-rebuild, contract-backend, test-backend, api-smoke, lint, typecheck, contract-frontend, test-frontend, e2e, orch-test, and make openapi all completed successfully after rerunning the startup/concurrency races serially.

### Risk Flags
- preview-is-structural-before-ingestion

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
