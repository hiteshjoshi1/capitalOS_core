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
