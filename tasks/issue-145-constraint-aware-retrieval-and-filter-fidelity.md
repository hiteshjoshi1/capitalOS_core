# Issue 145: Constraint-Aware Retrieval And Filter Fidelity

## Problem Statement

### What is wrong today

The retrieval stack is still too loose when the user gives **explicit constraints** such as:

- author: "Warren Buffett"
- date range: "from 2020 to 2025"
- source type: "letters"
- exact entity focus: "Charlie Munger"

Today, the system optimizes for "some evidence" rather than "evidence that actually respects the user's constraints."

This creates a real product problem:

- a query asking for Buffett **from 2020 to 2025** can return passages from 1986 or 2004
- a query asking what Buffett says about **Charlie Munger** can surface generic Buffett passages that do not discuss Munger
- retrieval-only testing is too weak because `/rag/retrieve` does not expose the same constraint behavior as AI Sage concept mode

This is not just a ranking issue and not just a recall issue.
It is a **constraint fidelity** issue.

### Why `141` and `142` are not enough

- `142` improves **candidate recall** via hybrid dense+sparse retrieval.
- `141` improves **candidate ranking precision** via a better reranker.

Those are both necessary, but neither one solves the policy bug where explicit constraints may be silently relaxed or may not be directly testable in retrieval-only mode.

If the system relaxes `2020-2025` to "any Buffett passage," the answer can still be wrong even if recall and reranking are otherwise strong.

### Evidence from code

#### 1) Retrieval-only API does not support explicit date/source filters

`POST /rag/retrieve` currently accepts:

```python
class RetrieveIn(BaseModel):
    query: str
    top_k: int = 5
    author_id: Optional[str] = None
    domains: Optional[list[str]] = None
    expertise_tags: Optional[list[str]] = None
```

There is no direct `year_from`, `year_to`, `published_from`, `published_to`, or `source_type` field in the retrieval-only contract.

That means the main no-LLM debug endpoint cannot directly test whether date/source constraints are being honored.

#### 2) Concept mode explicitly relaxes date/source constraints

In `api/app/rag/concept_mode.py`, `_retrieve_with_intent_fallback()` tries constrained retrieval first, then deliberately relaxes those constraints if the candidate set is thin.

The current behavior is roughly:

1. try exact `source_type + year_from + year_to`
2. try relaxed source type
3. try relaxed year range
4. try fully unconstrained

That behavior is useful for recall, but it is **wrong as a silent default** when the user explicitly requested a hard filter.

#### 3) Date filtering relies on chunk metadata, not a first-class document date contract

`api/app/rag/retrieval.py` currently filters with:

```python
(rc.metadata_json->>'year') >= :year_from
(rc.metadata_json->>'year') <= :year_to
```

This is weaker than a first-class document-level date contract because:

- it assumes `metadata_json["year"]` is reliably present
- it assumes string-comparison semantics are sufficient
- it does not expose whether the date was missing, inferred, or exact

The system should have a clearer, auditable path from document `published_at` to retrieval filters.

## Goal

Make explicit user constraints first-class and auditable in retrieval.

Specifically:

1. If the user explicitly specifies author/date/source constraints, retrieval should honor them by default.
2. If constraints are relaxed, that must be explicit in the response contract and visible to the caller.
3. Retrieval-only APIs must support those constraints directly so quality can be tested without LLM synthesis.
4. Document/chunk metadata must reliably support date-aware filtering.

## Current State (Code Evidence)

| Component | File | Current Behavior |
|-----------|------|------------------|
| Retrieval-only API | `api/app/routers/rag.py:/retrieve` | No direct date/source filters |
| Dense retrieval filters | `api/app/rag/retrieval.py:retrieve_similar_chunks()` | Filters on `metadata_json->>'year'` |
| Hybrid retrieval filters | `api/app/rag/retrieval.py:retrieve_keyword_chunks()` | Same metadata-based year filtering |
| Intent-aware fallback | `api/app/rag/concept_mode.py:_retrieve_with_intent_fallback()` | Silently relaxes explicit date/source constraints |
| Manual ingestion date input | `api/app/routers/rag.py` | Accepts `published_at` on manual ingest |
| Retrieval response transparency | API responses | Do not clearly indicate applied vs relaxed constraints |

## Proposed Technical Design

### 1) Add first-class retrieval constraints to retrieval-only APIs

Extend `POST /rag/retrieve` so it can directly accept:

```python
class RetrieveIn(BaseModel):
    query: str
    top_k: int = 5
    author_id: Optional[str] = None
    author_ids: Optional[list[str]] = None
    source_type: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    published_from: Optional[str] = None   # YYYY-MM-DD
    published_to: Optional[str] = None     # YYYY-MM-DD
    strict_constraints: bool = True
    domains: Optional[list[str]] = None
    expertise_tags: Optional[list[str]] = None
```

This endpoint should stay **no-LLM** and return raw evidence only.

### 2) Make constraint handling explicit, not silent

Introduce a response shape that makes the retrieval policy observable:

```python
{
  "query": "...",
  "constraints_requested": {
    "author_ids": ["warren_buffett"],
    "source_type": "letter",
    "year_from": 2020,
    "year_to": 2025
  },
  "constraints_applied": {
    "author_ids": ["warren_buffett"],
    "source_type": "letter",
    "year_from": 2020,
    "year_to": 2025
  },
  "constraints_relaxed": false,
  "constraint_relaxation_reason": null,
  "evidence_chunks": [...]
}
```

If the system relaxes constraints, that must be explicit:

```python
"constraints_relaxed": true,
"constraint_relaxation_reason": "No results under exact date filter; year filter removed after explicit opt-in."
```

### 3) Separate strict retrieval from fallback retrieval

The current concept-mode logic mixes two concerns:

- exact constrained retrieval
- fallback broadening for recall

These should be separated.

Proposed structure:

- `retrieve_with_constraints(...)`:
  exact retrieval only, no silent relaxation
- `retrieve_with_fallback(...)`:
  explicit staged fallback policy, only used when allowed by caller

Concept mode can still use fallback behavior, but only when the product decision is explicit and visible in the response.

### 4) Strengthen date filtering on real document metadata

Instead of relying only on `metadata_json["year"]`, retrieval should use a consistent, auditable date source:

- prefer `rag_documents.published_at` where available
- derive `year` from `published_at` during ingestion/backfill
- preserve the derived year in chunk metadata for convenience, but do not make it the only source of truth

If a document has no reliable date:

- retrieval should not pretend the date filter passed
- the response should indicate that some corpus items had missing date metadata

### 5) Add explicit retrieval diagnostics

For retrieval debugging and evaluation, add optional diagnostics:

```python
{
  "candidate_counts": {
    "before_filters": 120,
    "after_author_filter": 48,
    "after_source_filter": 20,
    "after_date_filter": 7
  },
  "filter_miss_reasons": {
    "missing_date_metadata": 3
  }
}
```

This should be available in retrieval-only mode behind a debug flag, not mixed into user-facing AI Sage output by default.

## Implementation Plan

### Step 1: Extend retrieval contracts
- Add `source_type`, `year_from`, `year_to`, `published_from`, `published_to`, `strict_constraints` to the retrieval-only request model.
- Add `constraints_requested`, `constraints_applied`, `constraints_relaxed`, `constraint_relaxation_reason` to retrieval responses.

### Step 2: Add a first-class constrained retrieval service
- Refactor retrieval code so exact constrained retrieval is a separate path from fallback broadening.
- Ensure dense, sparse, and hybrid retrieval all share the same constraint semantics.

### Step 3: Fix concept-mode fallback policy
- Update `_retrieve_with_intent_fallback()` so explicit constraints are not silently relaxed by default.
- If concept mode chooses to broaden, surface that decision in the returned intent/debug metadata.

### Step 4: Strengthen date metadata contract
- Audit ingestion so `published_at` consistently propagates from source/document into retrieval-visible metadata.
- Backfill or normalize year metadata from `published_at` where possible.
- Ensure missing/unknown dates are handled honestly.

### Step 5: Add retrieval diagnostics
- Add optional debug metadata for candidate counts and dropped-by-filter reasons.
- Keep debug output opt-in.

### Step 6: Tests
- Add retrieval-only tests for strict author/date/source filtering.
- Add concept-mode tests proving explicit date constraints are not silently ignored.
- Add tests for zero-result strict retrieval.
- Add tests for explicit fallback mode where relaxation is allowed and reported.

## Acceptance Criteria

- [ ] `POST /rag/retrieve` accepts direct author/date/source constraints without requiring AI Sage concept mode.
- [ ] Explicit date/source constraints are strict by default.
- [ ] If a retrieval path relaxes constraints, the response explicitly says so and explains why.
- [ ] Retrieval uses reliable date metadata derived from document `published_at` where available.
- [ ] Missing date metadata is surfaced honestly in diagnostics instead of silently treated as matching.
- [ ] Dense-only, sparse-only, and hybrid retrieval paths all honor the same constraint semantics.
- [ ] Existing retrieval APIs remain backward-compatible for callers that do not pass the new fields.
- [ ] Tests cover: exact date filtering, exact source filtering, strict zero-result behavior, explicit fallback behavior, and missing-date edge cases.

## Risks / Tradeoffs

| Risk | Mitigation |
|------|-----------|
| Strict filters may produce zero results more often | That is correct behavior; expose explicit fallback as a product choice |
| Existing AI Sage behavior may appear "worse" because it stops returning broad older passages | Better honesty and constraint fidelity outweigh fake recall |
| Date metadata may be incomplete for older ingested corpus | Add backfill/normalization path and diagnostics |
| More response metadata adds payload size | Keep diagnostics optional and compact |

## Test / Evaluation Plan

### Retrieval-only API tests
- Query Buffett with `year_from=2020`, `year_to=2025` and verify no 1986/2004 chunks are returned.
- Query with `source_type=letter` and verify non-letter sources are excluded.
- Query with `strict_constraints=true` and verify zero results remain zero.
- Query with `strict_constraints=false` and verify any relaxation is explicitly reported.

### Concept mode tests
- Query with explicit date intent and verify returned evidence respects the date range by default.
- Verify intent/debug metadata records whether fallback broadening occurred.

### Corpus metadata tests
- Verify documents with `published_at` produce retrievable year filters.
- Verify documents missing date metadata are excluded from strict date matches or explicitly counted as unknown.

## Out Of Scope

- Cross-encoder reranking itself (`141`)
- Hybrid dense+sparse retrieval itself (`142`)
- Broader answer-synthesis or critique improvements

This issue is specifically about **constraint fidelity and retrieval contract honesty**.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented Issue 145: Constraint-Aware Retrieval and Filter Fidelity. Extended POST /rag/retrieve with explicit author/date/source constraint fields, added ConstrainedRetrievalResult dataclass with transparency metadata, added retrieve_with_constraints() for strict/fallback retrieval separation, strengthened date filtering to prefer published_at over metadata_json year string, updated concept mode to surface constraint relaxation, and added ConceptQueryResult constraint tracking fields.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: POST /rag/retrieve accepts direct author/date/source constraints without requiring AI Sage concept mode
- Acceptance criterion: Explicit date/source constraints are strict by default (strict_constraints=True)
- Acceptance criterion: If a retrieval path relaxes constraints, the response explicitly says so and explains why
- Acceptance criterion: Retrieval uses reliable date metadata derived from document published_at where available (Postgres path)
- Acceptance criterion: Missing date metadata is handled honestly via OR fallback rather than silently treating as matching
- Acceptance criterion: Dense-only, sparse-only, and hybrid retrieval paths all honor the same constraint semantics via _apply_date_filters()
- Acceptance criterion: Existing retrieval APIs remain backward-compatible for callers that do not pass the new fields
- Acceptance criterion: Tests cover: exact date filtering, exact source filtering, strict zero-result behavior, explicit fallback behavior, missing-date edge cases, and constraint transparency fields

## Prepare
Checked out `feature/issue-145-constraint-aware-retrieval-and-filter-fidelity` from `main` and ensured task file exists.

## Plan Summary
Step 1: Extend retrieval contracts (RetrieveIn, RetrieveOut, ConstrainedRetrievalResult). Step 2: Add retrieve_with_constraints() with strict/fallback modes. Step 3: Add _apply_date_filters() using published_at on Postgres. Step 4: Update concept mode _retrieve_with_intent_fallback to return (chunks, relaxed, reason) tuple. Step 5: Surface relaxation in ConceptQueryResult and ConceptQueryOut. Step 6: Write tests. Step 7: Fix existing test assertions (year type str->int).

### Architecture Decisions
- strict_constraints=True is the default for /rag/retrieve (explicit API callers get strict behavior); concept mode still uses fallback internally but now surfaces relaxation metadata
- _apply_date_filters() uses EXTRACT(YEAR FROM rd.published_at) as the preferred date source on Postgres with OR fallback to metadata_json year string; SQLite uses metadata_json only
- retrieve_with_constraints() is a separate function that wraps retrieve_hybrid() with staged fallback policy—concept mode fallback logic is preserved but made transparent
- year_from/year_to are int throughout the retrieval layer; concept_mode converts intent string dates to int before calling retrieval
- ConstrainedRetrievalResult.as_dict() omits diagnostics key entirely when debug=False to keep payload compact
- Backward compatibility: /rag/retrieve falls back to old execute_retrieve() path when no constraint fields are set, preserving existing caller behavior

### Acceptance Criteria
- POST /rag/retrieve accepts direct author/date/source constraints without requiring AI Sage concept mode
- Explicit date/source constraints are strict by default (strict_constraints=True)
- If a retrieval path relaxes constraints, the response explicitly says so and explains why
- Retrieval uses reliable date metadata derived from document published_at where available (Postgres path)
- Missing date metadata is handled honestly via OR fallback rather than silently treating as matching
- Dense-only, sparse-only, and hybrid retrieval paths all honor the same constraint semantics via _apply_date_filters()
- Existing retrieval APIs remain backward-compatible for callers that do not pass the new fields
- Tests cover: exact date filtering, exact source filtering, strict zero-result behavior, explicit fallback behavior, missing-date edge cases, and constraint transparency fields

### Planned Paths
- `api/app/rag/retrieval.py`
- `api/app/rag/concept_mode.py`
- `api/app/routers/rag.py`
- `api/app/routers/ai_sage.py`
- `api/tests/test_rag_constraint_retrieval.py`

## Build Summary
Implemented Issue 145: Constraint-Aware Retrieval and Filter Fidelity. Extended POST /rag/retrieve with explicit author/date/source constraint fields, added ConstrainedRetrievalResult dataclass with transparency metadata, added retrieve_with_constraints() for strict/fallback retrieval separation, strengthened date filtering to prefer published_at over metadata_json year string, updated concept mode to surface constraint relaxation, and added ConceptQueryResult constraint tracking fields.

### Changed Files
- `api/app/rag/concept_mode.py`
- `api/app/rag/retrieval.py`
- `api/app/routers/ai_sage.py`
- `api/app/routers/rag.py`
- `api/tests/test_intent_router.py`
- `api/tests/test_rag_constraint_retrieval.py`
- `tasks/issue-145-constraint-aware-retrieval-and-filter-fidelity.md`

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
Implemented Issue 145: Constraint-Aware Retrieval and Filter Fidelity. Extended POST /rag/retrieve with explicit author/date/source constraint fields, added ConstrainedRetrievalResult dataclass with transparency metadata, added retrieve_with_constraints() for strict/fallback retrieval separation, strengthened date filtering to prefer published_at over metadata_json year string, updated concept mode to surface constraint relaxation, and added ConceptQueryResult constraint tracking fields.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` POST /rag/retrieve accepts direct author/date/source constraints without requiring AI Sage concept mode: RetrieveIn now includes author_ids, source_type, year_from, year_to, published_from, published_to, strict_constraints, debug; endpoint uses retrieve_with_constraints() when any constraint is set
- `pass` Explicit date/source constraints are strict by default: strict_constraints: bool = True is the default on RetrieveIn; retrieve_with_constraints() strict mode makes only one retrieval call with no fallback
- `pass` If a retrieval path relaxes constraints, the response explicitly says so and explains why: RetrieveOut includes constraints_relaxed and constraint_relaxation_reason; retrieve_with_constraints() populates these with staged relaxation reason strings; ConceptQueryResult/Out also include these fields
- `pass` Retrieval uses reliable date metadata derived from document published_at where available: _apply_date_filters() on Postgres uses EXTRACT(YEAR FROM rd.published_at) as primary source with OR fallback to metadata_json year string; preferred over metadata-only approach
- `pass` Missing date metadata is surfaced honestly in diagnostics instead of silently treated as matching: Postgres OR clause only matches documents where published_at IS NOT NULL (strong path) OR published_at IS NULL and metadata year matches (fallback); documents with neither are excluded from strict date filters; diagnostics exposed via debug=True
- `pass` Dense-only, sparse-only, and hybrid retrieval paths all honor the same constraint semantics: _apply_date_filters() is called from retrieve_similar_chunks(), retrieve_keyword_chunks(), and retrieve_hybrid() all accept year_from/year_to/published_from/published_to/source_type
- `pass` Existing retrieval APIs remain backward-compatible for callers that do not pass the new fields: All new fields are Optional with None defaults; /rag/retrieve falls back to execute_retrieve() when no constraint fields set; 579 existing tests all pass
- `pass` Tests cover: exact date filtering, exact source filtering, strict zero-result behavior, explicit fallback behavior, and missing-date edge cases: api/tests/test_rag_constraint_retrieval.py added with 35 tests covering ConstrainedRetrievalResult, strict mode, fallback mode, _apply_date_filters SQLite/Postgres paths, RetrieveIn/Out schemas, concept mode tuple return, ConceptQueryResult fields, backward compat

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
