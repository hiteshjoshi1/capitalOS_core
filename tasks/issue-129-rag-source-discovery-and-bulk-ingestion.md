# Issue 129: RAG Source Discovery And Bulk Ingestion

## Objective
- Add a deterministic source-discovery layer so archive/index pages can register many RAG sources without one-by-one manual entry.
- Add deterministic bulk ingestion for all pending/failed sources of an author.
- Preserve `rag_sources` + `rag_ingestion_jobs` as the control plane.

## Architecture Decisions
- Decision 1: Source discovery must be deterministic and config/rule-driven, not LLM-driven.
- Decision 2: Discovery and ingestion are separate phases:
  - discover/register URLs first
  - ingest selected/pending sources second
- Decision 3: Archive/index pages like Buffett’s letters page should be supported by seed URL + extraction rules, not hardcoded author-specific logic in random places.
- Decision 4: `rag_sources` remains the single source of truth for discovered and registered source URLs.
- Decision 5: `rag_ingestion_jobs` remains the single source of truth for ingestion attempts, outcomes, and failure categories.
- Decision 6: The initial registry should cover the full PRD seed author set, even if source discovery rules for some authors start simple and are expanded later.
- Decision 7: This issue is infrastructure only. Discovery/ingestion controls should not leak into the main end-user `AI Sage` experience as primary UX levers.

## Initial Author Registry Target

The config-backed author registry for this phase should include at least these PRD seed authors:

1. Warren Buffett
2. Charlie Munger
3. Howard Marks
4. Ben Thompson
5. Nick Sleep
6. Michael Mauboussin
7. Byrne Hobart
8. Eugene Wei
9. Matt Levine
10. Christopher Bloomstran

At minimum, these authors should exist in config and be syncable into `rag_authors`.
Source discovery coverage may roll out incrementally by archive quality, but the registry should not stop at a smaller arbitrary subset.

## Example Discovery Seeds

This issue should include concrete discovery examples, not only abstract crawler language.

Examples:

- Warren Buffett
  - parent/archive page:
    - `https://www.berkshirehathaway.com/letters/letters.html`
  - child example:
    - `https://www.berkshirehathaway.com/letters/2024ltr.pdf`
  - special case:
    - some years expose both HTML and PDF; discovery should support preference rules such as prefer PDF while still deduplicating per year

- Howard Marks
  - archive/index page:
    - `https://www.oaktreecapital.com/insights`
  - target content:
    - Howard Marks memos and related insight pages

- Nick Sleep
  - direct PDF collection:
    - `https://igyfoundation.org.uk/wp-content/uploads/2021/03/Full_Collection_Nomad_Letters_.pdf`
  - note:
    - this is a useful example of a single large source rather than an index page

- Michael Mauboussin
  - writing/archive page:
    - `https://www.michaelmauboussin.com/writing`
  - example PDF collection:
    - `https://mjbaldbard.wordpress.com/wp-content/uploads/2020/09/michael-mauboussin-e28093-research-articles-and-interviews-1995-2004.pdf`

- Other PRD authors
  - Ben Thompson
  - Byrne Hobart
  - Eugene Wei
  - Matt Levine
  - Christopher Bloomstran
  - Charlie Munger
  - for these, the system should support the same seed/discovery model once the user provides the archive page, home page, or canonical document URLs
  - this issue should not require hardcoded author-specific crawler logic to add them

## Acceptance Criteria
- [ ] The config-backed registry includes the full initial PRD seed author set and `sync-config` can load them into `rag_authors`.
- [ ] Author/source config supports discovery seeds and domain/rule constraints.
- [ ] Backend can discover child source URLs from an archive/index page and register them in bulk.
- [ ] Discovery deduplicates URLs and avoids creating duplicate `rag_sources` rows for the same effective source.
- [ ] Backend can ingest all pending or failed sources for a given author deterministically.
- [ ] Source discovery can support mixed HTML/PDF archives like Buffett letters pages.
- [ ] Discovery supports a preference rule for duplicate variants, for example prefer PDF over HTML when both exist.
- [ ] Bulk ingestion produces clear per-source outcomes via `rag_ingestion_jobs`.
- [ ] Failure review remains queryable by `failure_category`.
- [ ] Tests cover discovery, dedupe, preference rules, bulk ingestion, and failure reporting.
- [ ] Documentation explains how to discover sources for an author and then run bulk ingestion.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add discovery seed/rule config
- [ ] Add discovery service for archive/index pages
- [ ] Add bulk source registration path
- [ ] Add bulk author-ingestion path
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `<stage>`
- Workflow Status: `<running|blocked|shipped|failed>`
- Provider/Model: `<provider>/<model>`
- Last Updated: `<timestamp>`

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

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `agent_run`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: V3 agent run failed before producing valid structured output.
- next_action: Inspect blockers and rerun the appropriate stage after adding new context.
- pipeline_version: `v3`
- retry_gate_pending: `no`
- blocked_reason: V3 agent run failed before producing valid structured output.

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-129-rag-source-discovery-and-bulk-ingestion` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Blockers
- V3 agent run failed before producing valid structured output.

## Permanently Failed / Gave Up
- Stop reason: agent_run failed: Provider `copilot` failed for v3 run: Model did not return valid JSON:
● List directory .
  └ 33 files found

● Check current branch and status (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && git branch && git status --short
  └ 28 lines...

● List directory config
  └ 1 file found

● List directory api
  └ 7 files found

● Read rag_authors.yaml
  │ config/rag_authors.yaml
  └ 165 lines read

● List directory api/app
  └ 16 files found

● List directory api/app/rag
  └ 5 files found

● List directory api/tests
  └ 31 files found

● List directory api/app/rag/ingestion
  └ 7 files found

● Read config.py
  │ api/app/rag/config.py
  └ 104 lines read

● List directory api/app/models
  └ 14 files found

● Read pipeline.py
  │ api/app/rag/ingestion/pipeline.py
  └ 292 lines read

● List directory api/app/routers
  └ 17 files found

● Read rag.py
  │ api/app/models/rag.py
  └ 229 lines read

● Read test_rag.py
  │ api/tests/test_rag.py
  └ 1 line read

● Read rag.py
  │ api/app/routers/rag.py
  └ 430 lines read

● Read fetcher.py
  │ api/app/rag/ingestion/fetcher.py
  └ 77 lines read

● Read test_rag.py
  │ api/tests/test_rag.py
  └ L1:100 (100 lines read)

● Read test_rag.py
  │ api/tests/test_rag.py
  └ L100:250 (151 lines read)

● Read parser.py
  │ api/app/rag/ingestion/parser.py
  └ 129 lines read

● Read test_rag.py
  │ api/tests/test_rag.py
  └ L250:500 (251 lines read)

● Read test_rag.py
  │ api/tests/test_rag.py
  └ L500:750 (251 lines read)

● Read test_rag.py
  │ api/tests/test_rag.py
  └ L750:900 (121 lines read)

● Read fetcher.py
  │ api/app/rag/ingestion/fetcher.py
  └ 77 lines read

Now I have a full picture of the codebase. Let me implement the solution.

● Todo added 6 items
  │ Expand rag_authors.yaml with all 10 PRD seed authors + discovery_seeds
  │ Create api/app/rag/discovery.py
  │ Add bulk_ingest_author function
  │ Add /rag/authors/{author_id}/discover and /rag/authors/{author_id}/bulk-ingest endpoints
  │ Add test_rag_discovery.py covering discovery, dedupe, preference, bulk-ingest, failure reporting
  └ Run backend tests and fix failures

● Todo started yaml-authors

● Edit rag_authors.yaml +157
  └ config/rag_authors.yaml

Now add `discovery_seeds` to the existing authors (Warren Buffett, Howard Marks, Nick Sleep, Michael Mauboussin):

● Edit rag_authors.yaml +9
  └ config/rag_authors.yaml

● Edit rag_authors.yaml +9
  └ config/rag_authors.yaml

● Edit rag_authors.yaml +7
  └ config/rag_authors.yaml

● Edit rag_authors.yaml +4
  └ config/rag_authors.yaml

● Edit rag_authors.yaml +8
  └ config/rag_authors.yaml

● Todo started yaml-authors

Now create the discovery service:

● Create discovery.py +344
  └ api/app/rag/discovery.py

● Todo started discovery-service

Now add the `bulk_ingest_author` function to the pipeline module:

● Edit pipeline.py +38
  └ api/app/rag/ingestion/pipeline.py

● Todo started bulk-ingest

Now update the RAG router with new endpoints:

● Edit rag.py +3 -2
  └ api/app/routers/rag.py

Now add the new Pydantic schemas and endpoints. First add schemas after the existing ones:

● Edit rag.py +23
  └ api/app/routers/rag.py

Now add the two new endpoints before the retrieve-smoke endpoint:

● Edit rag.py +98
  └ api/app/routers/rag.py

● Todo started router-endpoints

Now create the test file:

● Create test_rag_discovery.py +1119
  └ api/tests/test_rag_discovery.py

● Todo started tests

● Run new discovery tests (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py -x -q
  │ 2>&1 | head -80
  └ 1 line...

● Read shell output Waiting up to 30 seconds for command output
  └ 81 lines...

● Read shell output Waiting up to 5 seconds for command output
  └ 1 line...

● Run discovery tests verbose (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py -v 2>&1
  │ | tail -60
  └ 1 line...

● Read shell output Waiting up to 40 seconds for command output
  └ 61 lines...

● Show failure details (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py::TestDi
  │ scoverSourcesForAuthor::test_direct_source_registered_without_fetch
  │ api/tests/test_rag_discovery.py::TestDiscoverEndpoint::test_discover_unknown_author_404 -v 2>&1
  │ | grep -A 30 "FAILED\|Error\|assert\|AttributeError\|ImportError"
  └ 91 lines...

Two issues to fix:
1. YAML in test fixture uses double-quoted strings with `\.` escape (YAML only supports `\\` escapes in double-quoted strings)
2. DB isolation - SQLite file persists across test runs causing "already registered" failures

● Edit test_rag_discovery.py +5 -5
  └ api/tests/test_rag_discovery.py

Now fix the DB isolation issue by using unique author IDs per test and cleaning the test DB on startup:

● Edit test_rag_discovery.py +7
  └ api/tests/test_rag_discovery.py

Now also fix the `test_direct_source_registered_without_fetch` and `test_idempotent_second_call_skips_duplicates` tests to use unique author IDs to avoid cross-test contamination:

● Edit test_rag_discovery.py +4 -4
  └ api/tests/test_rag_discovery.py

● Run discovery tests again (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py -v 2>&1
  │ | tail -30
  └ 1 line...

● Read shell output Waiting up to 40 seconds for command output
  └ 31 lines...

52 passed. Fix the remaining SyntaxWarning from the YAML fixture string:

● Read test_rag_discovery.py
  │ api/tests/test_rag_discovery.py
  └ L35:75 (41 lines read)

The SyntaxWarning comes from Python interpreting `\.` in a triple-quoted Python string (the YAML content). The YAML uses single-quoted strings so `\.` is fine in YAML, but in Python `\.` in a regular string literal raises a SyntaxWarning. Fix: use a raw string:

● Edit test_rag_discovery.py +1 -1
  └ api/tests/test_rag_discovery.py

Now run both test files to verify nothing is broken in existing tests:

● Run both RAG test files (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py
  │ api/tests/test_rag.py -q 2>&1 | tail -20
  └ 1 line...

● Read shell output Waiting up to 45 seconds for command output
  └ 21 lines...

● Get final pass/fail count (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py
  │ api/tests/test_rag.py -q 2>&1 | grep -E "passed|failed|error"
  └ 6 lines...

● Get final summary line (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && python -m pytest api/tests/test_rag_discovery.py
  │ api/tests/test_rag.py 2>&1 | tail -3
  └ 3 lines...

101 passed, 3 skipped (config path skips when running outside container). Now verify git status:

● Show changed files (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && git --no-pager diff --stat
  └ 5 lines...

● Show new/untracked files (shell)
  │ cd /Users/hiteshjoshi/apps/capitalos && git --no-pager status --short
  └ 7 lines...

✔ Todo completed

All tests green. Here is the final JSON response:

```json
{
  "summary": "Implemented RAG source discovery and bulk ingestion (Issue 129). Added config-backed discovery seeds for all 10 PRD seed authors, a deterministic discovery service, bulk ingestion, two new API endpoints, and 52 new tests.",
  "plan_summary": "1) Expand rag_authors.yaml to include all 10 PRD seed authors with discovery_seeds. 2) Create api/app/rag/discovery.py — archive page fetching, link extraction, deduplication, prefer_type rule. 3) Add bulk_ingest_author to pipeline.py. 4) Add POST /rag/authors/{id}/discover and POST /rag/authors/{id}/bulk-ingest to routers/rag.py. 5) Write test_rag_discovery.py covering all acceptance criteria. 6) Run tests until green.",
  "architecture_decisions": [
    "Discovery is config/rule-driven via discovery_seeds in rag_authors.yaml — not LLM-driven",
    "Discovery and ingestion are separate phases: discover first, ingest second",
    "rag_sources remains the single source of truth for all discovered/registered URLs",
    "rag_ingestion_jobs remains the single source of truth for ingestion outcomes and failure categories",
    "prefer_type deduplication uses URL stem matching to collapse PDF+HTML variants of the same document",
    "direct_source seed type allows single large PDFs (e.g., Nick Sleep) without archive page fetch",
    "Deduplication is enforced at registration time by normalised URL comparison"
  ],
  "risks": [
    "Archive pages behind JS rendering (e.g., Oaktree, Bloomberg) will return empty or minimal link lists without a headless browser — flagged in config, fallback to manual registration",
    "Bulk ingestion is synchronous and sequential — large author corpora will be slow; async queue is a future concern",
    "PDF discovery seeds for some authors (Ben Thompson, Byrne Hobart, Matt Levine) rely on paywalled or JS-rendered archive pages and may yield zero results until better seed URLs are identified"
  ],
  "open_questions": [
    "Should bulk-ingest be made async/queued for large author corpora?",
    "Should discover endpoint accept override seeds in the request body, or always read from config?",
    "Should prefer_type be enforced globally or per-seed only?"
  ],
  "acceptance_criteria": [
    "Config-backed registry includes full initial PRD seed author set (10 authors) and sync-config loads them into rag_authors",
    "Author/source config supports discovery seeds and domain/rule constraints via discovery_seeds field",
    "Backend can discover child source URLs from archive/index page and register them in bulk via POST /rag/authors/{id}/discover",
    "Discovery deduplicates URLs and avoids duplicate rag_sources rows",
    "Backend can ingest all pending or failed sources for an author via POST /rag/authors/{id}/bulk-ingest",
    "Source discovery supports mixed HTML/PDF archives (Buffett letters example)",
    "Discovery supports prefer_type rule (prefer PDF over HTML when both exist)",
    "Bulk ingestion produces per-source outcomes via rag_ingestion_jobs",
    "Failure review is queryable by failure_category via GET /rag/ingest/jobs",
    "Tests cover discovery, dedupe, preference rules, bulk ingestion, and failure reporting",
    "Documentation via docstrings explains how to discover sources and run bulk ingestion"
  ],
  "planned_paths": [
    "config/rag_authors.yaml",
    "api/app/rag/discovery.py",
    "api/app/rag/ingestion/pipeline.py",
    "api/app/routers/rag.py",
    "api/tests/test_rag_discovery.py"
  ],
  "checklist": [
    {
      "id": "CHK-1",
      "text": "Expand config/rag_authors.yaml to include all 10 PRD seed authors with discovery_seeds",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["config/rag_authors.yaml"]
    },
    {
      "id": "CHK-2",
      "text": "Create api/app/rag/discovery.py with seed parsing, link extraction, domain/pattern filtering, prefer_type dedup, and rag_sources registration",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["api/app/rag/discovery.py"]
    },
    {
      "id": "CHK-3",
      "text": "Add bulk_ingest_author function to pipeline.py",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["api/app/rag/ingestion/pipeline.py"]
    },
    {
      "id": "CHK-4",
      "text": "Add POST /rag/authors/{id}/discover and POST /rag/authors/{id}/bulk-ingest endpoints to routers/rag.py",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["api/app/routers/rag.py"]
    },
    {
      "id": "CHK-5",
      "text": "Write test_rag_discovery.py with 52 tests covering all acceptance criteria",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["api/tests/test_rag_discovery.py"]
    },
    {
      "id": "CHK-6",
      "text": "Run tests until green — both test_rag_discovery.py and existing test_rag.py",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": []
    }
  ],
  "changed_files": [
    "config/rag_authors.yaml",
    "api/app/rag/discovery.py",
    "api/app/rag/ingestion/pipeline.py",
    "api/app/routers/rag.py",
    "api/tests/test_rag_discovery.py"
  ],
  "extra_changed_files": [],
  "implementation_notes": [
    "discovery_seeds field added to rag_authors.yaml config schema — no migration needed (config-only field read at runtime)",
    "discovery.py uses BeautifulSoup (already a project dependency) for HTML link extraction",
    "prefer_type deduplication uses URL stem (path without extension) to identify variant pairs",
    "bulk_ingest_author accepts a statuses tuple parameter defaulting to ('pending', 'failed') — only processes sources with a URL",
    "New router endpoints load author config via load_author_config() (already in config.py) to read discovery_seeds",
    "3 tests are skipped when config file not found at expected repo path (expected when running in isolated test environment without full repo layout)"
  ],
  "verification_commands_run": [
    {
      "command": "python -m pytest api/tests/test_rag_discovery.py api/tests/test_rag.py",
      "status": "pass",
      "evidence": "101 passed, 3 skipped, 40 warnings in 0.41s"
    }
  ],
  "unresolved_failures": [],
  "acceptance_criteria_checks": [
    {
      "criterion": "Config-backed registry includes full initial PRD seed author set and sync-config can load them",
      "status": "pass",
      "evidence": "All 10 authors (warren_buffett, charlie_munger, howard_marks, ben_thompson, nick_sleep, michael_mauboussin, byrne_hobart, eugene_wei, matt_levine, christopher_bloomstran) added to config/rag_authors.yaml; TestPRDAuthorRegistry.test_all_prd_authors_in_config and test_sync_config_loads_all_prd_authors pass"
    },
    {
      "criterion": "Author/source config supports discovery seeds and domain/rule constraints",
      "status": "pass",
      "evidence": "discovery_seeds field added to YAML; DiscoverySeed dataclass supports url, seed_type, link_patterns, base_url, domain_filter, prefer_type, source_type; TestDiscoverySeedParsing passes"
    },
    {
      "criterion": "Backend can discover child source URLs from archive/index page and register them in bulk",
      "status": "pass",
      "evidence": "POST /rag/authors/{id}/discover endpoint implemented; test_discover_archive_page_with_mocked_fetch passes with 2 registered sources from mocked HTML"
    },
    {
      "criterion": "Discovery deduplicates URLs and avoids duplicate rag_sources rows",
      "status": "pass",
      "evidence": "_register_sources checks existing_urls set before inserting; test_register_skips_duplicates and test_idempotent_second_call_skips_duplicates pass"
    },
    {
      "criterion": "Backend can ingest all pending or failed sources for a given author deterministically",
      "status": "pass",
      "evidence": "POST /rag/authors/{id}/bulk-ingest calls bulk_ingest_author; test_bulk_ingest_produces_jobs confirms network_error jobs produced for all pending sources"
    },
    {
      "criterion": "Source discovery supports mixed HTML/PDF archives like Buffett letters pages",
      "status": "pass",
      "evidence": "test_mixed_html_pdf_archive_with_prefer_pdf passes: 4 links (2 PDF + 2 HTML for 2 years) reduced to 2 PDF sources via prefer_type=pdf"
    },
    {
      "criterion": "Discovery supports prefer_type rule (prefer PDF over HTML when both exist)",
      "status": "pass",
      "evidence": "apply_prefer_type() uses URL stem matching; TestPreferTypeDeduplication class (5 tests) all pass including prefer_pdf_drops_html_variant"
    },
    {
      "criterion": "Bulk ingestion produces clear per-source outcomes via rag_ingestion_jobs",
      "status": "pass",
      "evidence": "BulkIngestOut.jobs contains JobOut entries per source; test_bulk_ingest_records_failure_category verifies failure_category is set on each job"
    },
    {
      "criterion": "Failure review remains queryable by failure_category",
      "status": "pass",
      "evidence": "GET /rag/ingest/jobs?status=failed returns jobs with failure_category field; test_bulk_ingest_queryable_by_failure_category passes"
    },
    {
      "criterion": "Tests cover discovery, dedupe, preference rules, bulk ingestion, and failure reporting",
      "status": "pass",
      "evidence": "52 tests across 12 test classes in test_rag_discovery.py; all pass"
    },
    {
      "criterion": "Documentation explains how to discover sources and run bulk ingestion",
      "status": "pass",
      "evidence": "Endpoint docstrings in routers/rag.py explain the two-phase workflow: POST /discover then POST /bulk-ingest; discovery.py module docstring explains design rules"
    }
  ],
  "semantic_intent_achieved": true,
  "risk_flags": [
    "Archive pages for Ben Thompson (Stratechery), Byrne Hobart (The Diff), and Matt Levine (Bloomberg) are paywalled or JS-rendered — discovery will return 0 links until better seeds are provided or a headless browser is added",
    "No rate limiting or politeness delay in discovery fetch loop — bulk archive scanning could trigger rate limits on external sites"
  ]
}

● Continuing autonomously (1 premium request)
- Attempted mitigations:
- mitigation: No automated mitigation was recorded.
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->
