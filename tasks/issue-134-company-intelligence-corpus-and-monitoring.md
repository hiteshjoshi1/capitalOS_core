# Issue 134: Company Intelligence Corpus And Monitoring

## Objective
- Build the first company-intelligence corpus that complements thinker writings.
- Let CapitalOS ingest and retrieve company-specific evidence such as filings, transcripts, presentations, product updates, and competitor signals.
- Make `AI Sage` and later decision memos capable of reasoning over both thinker wisdom and company evidence.

## Program Position
- Depends on issue 130 for retrieval infrastructure.
- Strongly complements issue 132 and issue 133.
- Supplies evidence required for better company analysis and better investment decisions.

## Architecture Decisions
- Keep thinker corpus and company corpus conceptually distinct, even if both use shared retrieval infrastructure.
- Company-intelligence ingestion should be deterministic and source-traceable.
- Focus on foundation sources first:
  - transcripts
  - filings / annual letters
  - investor presentations
  - company blog / product updates
  - competitor source links where feasible
- Do not overpromise real-time streaming. Batch ingestion and refresh is enough for the initial issue.

## Acceptance Criteria
- [ ] Add company source registry and ingestion path for core company documents.
- [ ] Retrieval can query thinker corpus, company corpus, or both.
- [ ] `AI Sage` can surface company evidence distinctly from thinker evidence.
- [ ] Add company-context retrieval mode that supports:
  - company profile question
  - business quality question
  - risk/competition question
  - what-changed question
- [ ] Add metadata and filtering for:
  - company / ticker
  - document type
  - document date
  - competitor / related company when available
- [ ] Add tests for:
  - company source ingestion
  - company evidence retrieval
  - mixed corpus retrieval

## Suggested Implementation Shape
- New persisted objects, names subject to judgment:
  - `company_sources`
  - `company_documents`
  - `company_chunks`
  - or reuse existing RAG tables with robust corpus typing and metadata
- Likely endpoints:
  - `POST /company-intel/sources`
  - `POST /company-intel/ingest`
  - `POST /company-intel/retrieve`
  - `POST /company-intel/analyze-context`

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- Ingest a sample company document set
- `curl -X POST http://localhost:8000/company-intel/retrieve -H "Content-Type: application/json" -d '{"company":"GOOGL","query":"capital allocation and competitive moat","top_k":5}'`
- Verify `AI Sage` can show company evidence alongside thinker evidence

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
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
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
