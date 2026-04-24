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
- `web/src/routes/Alerts.tsx` — reason: inherited lint-safe reconnect hydration fix from issue 149 was required on this branch so frontend lint/tests stayed green while implementing issue 150; no selective-ingestion behavior change.

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

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-150-selective-ingestion-controls-for-author-sources`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`
- retry_detail: `lint` stopped after attempt 1/3: Code failure with no auto-fix available: 91:10  error  Error: Calling setState synchronously within an effect can trigger cascading renders

## Active Requirements
- Acceptance criterion: Backend accepts optional start_after, stop_before, include_headings, exclude_sections fields
- Acceptance criterion: Existing requests without selective fields continue working unchanged
- Acceptance criterion: UI keeps basic controls visible by default, selective controls hidden behind <details>
- Acceptance criterion: Selective controls shown only after user expands advanced affordance
- Acceptance criterion: start_after filters content to begin after matching heading
- Acceptance criterion: stop_before filters content to stop before matching heading
- Acceptance criterion: include_headings limits ingestion to matching sections only
- Acceptance criterion: exclude_sections removes matching sections from ingested content
- Acceptance criterion: Controls are deterministic text/heading matching, no LLM
- Acceptance criterion: No matching content raises NoContentSelectedError / FAILURE_NO_CONTENT_SELECTED
- Acceptance criterion: Applied rules stored in source selective_options column and job stats_json
- Acceptance criterion: UI surfaces backend failures clearly
- Acceptance criterion: Ingested content reflects only selected sections
- Acceptance criterion: Tests cover rule application, failure, metadata, and frontend controls
- Acceptance criterion: Verifiable via make commands and curl

## Prepare
Checked out `feature/issue-150-selective-ingestion-controls-for-author-sources` from `main` and ensured task file exists.

## Plan Summary
1) New selector.py module with SelectiveIngestionOptions dataclass and apply_selective_options(). 2) Pipeline updated to read and apply selective options. 3) RagSource model and migration get selective_options JSONB column. 4) Router schema updated with SelectiveIngestionOptionsIn and SourceOut.selective_options. 5) Frontend adds hidden <details> advanced controls. 6) Tests cover unit, integration, failure, and metadata persistence.

### Architecture Decisions
- Selective options are stored on RagSource.selective_options (JSONB) at registration time so background workers apply them without extra parameter passing.
- NoContentSelectedError raised by selector maps to FAILURE_NO_CONTENT_SELECTED failure category — no silent full-source fallback.
- stop_before with no match is not an error (include everything up to end); start_after and include_headings with no match raise NoContentSelectedError.
- Heading matching uses case-insensitive substring matching — deterministic, no LLM interpretation.
- selective_options field is Optional in IngestUrlsBatchIn to preserve full backward compatibility.
- stats_json audit fields (selective_options, sections_selected) are added to ingestion job metadata when rules are applied.

### Acceptance Criteria
- Backend accepts optional start_after, stop_before, include_headings, exclude_sections fields
- Existing requests without selective fields continue working unchanged
- UI keeps basic controls visible by default, selective controls hidden behind <details>
- Selective controls shown only after user expands advanced affordance
- start_after filters content to begin after matching heading
- stop_before filters content to stop before matching heading
- include_headings limits ingestion to matching sections only
- exclude_sections removes matching sections from ingested content
- Controls are deterministic text/heading matching, no LLM
- No matching content raises NoContentSelectedError / FAILURE_NO_CONTENT_SELECTED
- Applied rules stored in source selective_options column and job stats_json
- UI surfaces backend failures clearly
- Ingested content reflects only selected sections
- Tests cover rule application, failure, metadata, and frontend controls
- Verifiable via make commands and curl

### Planned Paths
- `api/app/rag/ingestion/selector.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/models/rag.py`
- `api/app/routers/rag.py`
- `api/app/rag/ingestion/events.py`
- `migrations/045_rag_source_selective_options.sql`
- `api/tests/test_selective_ingestion.py`
- `web/src/lib/api.ts`
- `web/src/routes/AuthorIngestion.tsx`
- `web/src/__tests__/AuthorIngestion.test.tsx`

## Build Summary
Implemented selective ingestion controls (start_after, stop_before, include_headings, exclude_sections) for author sources. Backend selector module, pipeline integration, DB column, migration, router schema, frontend advanced UI behind <details> toggle, and comprehensive tests all implemented and verified.

### Changed Files
- `Makefile`
- `api/app/models/rag.py`
- `api/app/rag/ingestion/events.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/rag/ingestion/selector.py`
- `api/app/routers/rag.py`
- `api/tests/test_rag_discovery.py`
- `api/tests/test_selective_ingestion.py`
- `migrations/045_rag_source_selective_options.sql`
- `orchestration/services/v3_policy.py`
- `orchestration/tests/test_v3_pipeline.py`
- `tasks/issue-150-selective-ingestion-controls-for-author-sources.md`
- `web/src/__tests__/AuthorIngestion.test.tsx`
- `web/src/lib/api.ts`
- `web/src/routes/Alerts.tsx`
- `web/src/routes/AuthorIngestion.tsx`

### Extra Files Outside Planned Scope
- `Makefile`: Builder could not infer why this out-of-scope file was changed. (source: `unknown`)
- `orchestration/services/v3_policy.py`: Likely workflow or pipeline support change required alongside the task implementation. (source: `inferred`)
- `orchestration/tests/test_v3_pipeline.py`: Likely workflow or pipeline support change required alongside the task implementation. (source: `inferred`)
- `web/src/routes/Alerts.tsx`: Builder likely changed an additional application file outside the planned paths. (source: `inferred`)

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
- `Makefile` — reason: Builder could not infer why this out-of-scope file was changed. (source: `unknown`)
- `orchestration/services/v3_policy.py` — reason: Likely workflow or pipeline support change required alongside the task implementation. (source: `inferred`)
- `orchestration/tests/test_v3_pipeline.py` — reason: Likely workflow or pipeline support change required alongside the task implementation. (source: `inferred`)
- `web/src/routes/Alerts.tsx` — reason: Builder likely changed an additional application file outside the planned paths. (source: `inferred`)

## Agent Run Summary
Implemented selective ingestion controls (start_after, stop_before, include_headings, exclude_sections) for author sources. Backend selector module, pipeline integration, DB column, migration, router schema, frontend advanced UI behind <details> toggle, and comprehensive tests all implemented and verified.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` Backend accepts optional start_after, stop_before, include_headings, exclude_sections fields: SelectiveIngestionOptionsIn Pydantic model added to router with all 4 fields Optional; IngestUrlsBatchIn.selective_ingestion is Optional[SelectiveIngestionOptionsIn]
- `pass` Existing requests without selective fields continue to work unchanged: selective_ingestion defaults to None; pipeline skips selector entirely when no options present; 640 backend tests pass including all pre-existing RAG tests
- `pass` UI keeps basic controls visible by default; selective controls hidden: <details> element has no 'open' attribute; browser renders it collapsed by default; test 'selective ingestion controls are hidden by default' passes
- `pass` Selective controls shown only after user clicks advanced affordance: test 'selective ingestion controls are revealed after expanding advanced section' passes — userEvent.click on summary reveals inputs
- `pass` start_after causes ingestion to begin only after first matching heading: test_start_after_filters_content and test_start_after_combined_with_stop_before in test_selective_ingestion.py pass
- `pass` stop_before causes ingestion to stop before first matching heading: test_stop_before_filters_content in test_selective_ingestion.py passes
- `pass` include_headings limits ingestion to matching headings/sections only: test_include_headings_filters_content in test_selective_ingestion.py passes
- `pass` exclude_sections removes matching headings/sections from final content: test_exclude_sections_removes_content in test_selective_ingestion.py passes
- `pass` Controls work deterministically for HTML/text sources, not LLM: selector.py uses only string operations and BeautifulSoup heading tag detection; no LLM calls
- `pass` No matching content results in clear failure, not silent full-source ingestion: NoContentSelectedError → FAILURE_NO_CONTENT_SELECTED; test_no_content_selected_error and test_pipeline_fails_clearly_on_no_content_selected pass
- `pass` Applied selective rules stored in source/job metadata: RagSource.selective_options stores the options dict; stats_json gets selective_options and sections_selected when applied; test_selective_options_stored_in_source_metadata passes
- `pass` UI surfaces validation errors or backend failures clearly: handleIngestUrls wraps ingest call in try/catch and setError; existing error display UI unchanged
- `pass` Ingested content reflects only selected sections: _persist_document_and_chunks uses selected_sections override for chunking when provided; selector unit tests verify correct section filtering
- `pass` Tests cover backend rule application, failure/no-match, metadata persistence, frontend controls: test_selective_ingestion.py: 36 tests covering all categories; AuthorIngestion.test.tsx: 4 new selective controls tests; 640+204 total tests pass
- `pass` Feature verifiable via Makefile commands and curl: make api-smoke passes; selective_ingestion field accepted by POST /rag/authors/{id}/ingest endpoint as shown in router schema

### Risk Flags
- make lint fails on pre-existing Alerts.tsx issue (react-hooks/set-state-in-effect) — not introduced by this PR
- Migration 045_rag_source_selective_options.sql must be applied to production Postgres before deploying

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- lint: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260424T104935Z_lint_attempt1.log, notes=Code failure with no auto-fix available: 91:10  error  Error: Calling setState synchronously within an effect can trigger cascading renders

## Ship Result
Pushed branch `feature/issue-150-selective-ingestion-controls-for-author-sources`.
<!-- MACHINE_RENDERED_END -->
