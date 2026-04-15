# Issue 144: PRD Consolidation for Ingestion, Retrieval, and Eval

## Objective
- Rewrite and streamline Module 2 architecture PRDs into one coherent, implementation-ready structure.
- Produce three clearly demarcated final PRDs:
  - PRD 2: Ingestion
  - PRD 3: Retrieval
  - PRD 4: Eval
- Use existing docs/issues as source inputs so architecture intent is preserved and contradictions are resolved.

## Inputs To Synthesize
- `PRD-Module-2-Investment-Intelligence-RAG.md`
- `PRD-module-2.1-intelligence-retrieval.md`
- `PRD-Platform-Intelligence-Strategy.md`
- `tasks/issue-128-thinker-ingestion-foundation.md`
- `tasks/issue-129-rag-source-discovery-and-bulk-ingestion.md`
- `tasks/issue-130-intelligence-retrieval-and-author-wisdom.md`
- `tasks/issue-131-decision-copilot-memos-and-calibration.md`
- `tasks/issue-132-multi-lens-reasoning-synthesis-and-critic.md`
- `tasks/issue-133-guided-investment-intake-and-decision-memos.md`
- `tasks/issue-134-company-intelligence-corpus-and-monitoring.md`
- `tasks/issue-135-feedback-outcome-review-and-personal-improvement-loop.md`
- `tasks/issue-136-auth-session-reliability-breakfix.md`
- `tasks/issue-137-ai-sage-intent-routing-and-query-understanding.md`
- `tasks/issue-138-ai-sage-retrieval-quality-reranking-and-context-expansion.md`
- `tasks/issue-139-advanced-document-parsing.md`
- `tasks/issue-140-recursive-and-semantic-chunking.md`
- `tasks/issue-141-cross-encoder-reranking.md`
- `tasks/issue-142-hybrid-dense-sparse-retrieval.md`
- `tasks/issue-143-retrieval-evaluation-harness.md`

## Architecture Decisions
- Decision 1: Final architecture is split by lifecycle, not by historical issue order:
  - PRD 2 = data ingestion and corpus formation
  - PRD 3 = query-time retrieval and synthesis stack
  - PRD 4 = evaluation, quality gates, and continuous improvement loop
- Decision 2: Preserve user-value-first sequencing and ruthless scope control:
  - keep only architecture that improves output quality now
  - defer scaffolding-only ideas into explicit deferred sections
- Decision 3: Each PRD must be implementation-ready with:
  - in-scope/out-of-scope boundaries
  - end-to-end flows
  - APIs/contracts where relevant
  - testability and acceptance criteria
  - dependencies on previous PRDs

## Required Deliverables
- New PRD doc for ingestion:
  - `PRD-2-Ingestion.md`
- New PRD doc for retrieval:
  - `PRD-3-Retrieval.md`
- New PRD doc for eval:
  - `PRD-4-Eval.md`

## PRD Structure Requirements (for each of 2/3/4)
- Problem statement and user jobs
- System boundaries (in scope / out of scope)
- Architecture and flow diagram in text form
- Data model concepts and key entities
- API/workflow contracts
- Quality requirements and failure behavior
- Acceptance criteria
- Verification plan (deterministic checks + scenario checks)
- Explicit dependency map to adjacent PRDs

## Acceptance Criteria
- [ ] Exactly three final PRDs are produced with clear boundaries: Ingestion (2), Retrieval (3), Eval (4).
- [ ] Content from issues 128–143 is absorbed into the correct PRD sections, with emphasis on issues 139–143.
- [ ] Duplicated or contradictory requirements across old PRDs/issues are reconciled and called out explicitly.
- [ ] Each PRD is implementation-ready: clear scope, contracts, acceptance criteria, and verification approach.
- [ ] Deferred items are captured explicitly and do not pollute near-term architecture.
- [ ] Existing PRD files are not deleted in this issue (user will manually delete after review).
- [ ] Changes are docs-only; no application code behavior changes.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `implement`
- Workflow Status: `running`
- Provider/Model: `anthropic/claude-opus-4.6`
- Last Updated: `2026-04-15T12:52:00Z`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` — docs-only change, no application code
- `typecheck`: `skip` — docs-only change, no application code
- `tests`: `skip` — docs-only change, no application code
- `e2e`: `skip` — docs-only change, no application code
- `api-smoke`: `skip` — docs-only change, no application code
- `policy-checks`: `pass` — three PRDs created; no existing files deleted; no code changes

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
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-144-prd-consolidation-ingestion-retrieval-eval`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-opus-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Exactly three final PRDs produced with clear boundaries: Ingestion (2), Retrieval (3), Eval (4)
- Acceptance criterion: Content from issues 128-143 absorbed into correct PRD sections, with emphasis on 139-143
- Acceptance criterion: Duplicated/contradictory requirements reconciled and called out in Reconciliation Notes sections
- Acceptance criterion: Each PRD is implementation-ready: clear scope, contracts, acceptance criteria, verification approach
- Acceptance criterion: Deferred items captured explicitly in §12/§13/§14 and do not pollute near-term architecture
- Acceptance criterion: Existing PRD files not deleted
- Acceptance criterion: Changes are docs-only; no application code behavior changes

## Prepare
Checked out `feature/issue-144-prd-consolidation-ingestion-retrieval-eval` from `main` and ensured task file exists.

## Plan Summary
Read all 19 source documents, classify content by lifecycle stage (ingestion/retrieval/eval), resolve contradictions, produce three implementation-ready PRDs with all required sections.

### Architecture Decisions
- Split by lifecycle: PRD 2 = ingestion/corpus formation, PRD 3 = query-time retrieval/synthesis, PRD 4 = evaluation/quality gates
- Preserve user-value-first sequencing: only architecture that improves output quality now; defer scaffolding
- Each PRD is self-contained with in-scope/out-of-scope, contracts, acceptance criteria, verification plan, and dependency map

### Acceptance Criteria
- Exactly three final PRDs produced with clear boundaries: Ingestion (2), Retrieval (3), Eval (4)
- Content from issues 128-143 absorbed into correct PRD sections, with emphasis on 139-143
- Duplicated/contradictory requirements reconciled and called out in Reconciliation Notes sections
- Each PRD is implementation-ready: clear scope, contracts, acceptance criteria, verification approach
- Deferred items captured explicitly in §12/§13/§14 and do not pollute near-term architecture
- Existing PRD files not deleted
- Changes are docs-only; no application code behavior changes

### Planned Paths
- `PRD-2-Ingestion.md`
- `PRD-3-Retrieval.md`
- `PRD-4-Eval.md`
- `tasks/issue-144-prd-consolidation-ingestion-retrieval-eval.md`

## Build Summary
Created three consolidated PRDs (PRD-2-Ingestion.md, PRD-3-Retrieval.md, PRD-4-Eval.md) by synthesizing content from 3 existing PRDs and 16 task files (issues 128-143). Each PRD has clear lifecycle boundaries, full required sections, reconciliation notes resolving contradictions, and explicit deferred items.

### Changed Files
- `PRD-2-Ingestion.md`
- `PRD-3-Retrieval.md`
- `PRD-4-Eval.md`
- `tasks/issue-144-prd-consolidation-ingestion-retrieval-eval.md`

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
Created three consolidated PRDs (PRD-2-Ingestion.md, PRD-3-Retrieval.md, PRD-4-Eval.md) by synthesizing content from 3 existing PRDs and 16 task files (issues 128-143). Each PRD has clear lifecycle boundaries, full required sections, reconciliation notes resolving contradictions, and explicit deferred items.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-opus-4.6`

### Semantic Checks
- `pass` Exactly three final PRDs produced with clear boundaries: Ingestion (2), Retrieval (3), Eval (4): PRD-2-Ingestion.md (413 lines), PRD-3-Retrieval.md (607 lines), PRD-4-Eval.md (474 lines) created with explicit lifecycle boundaries in §0 of each.
- `pass` Content from issues 128-143 absorbed into correct PRD sections, with emphasis on 139-143: All 16 issues referenced and absorbed: 128,129,134,139,140→PRD2; 130,131,132,133,137,138,141,142→PRD3; 143,135→PRD4; 136 noted as orthogonal. Each PRD has Issue Traceability table.
- `pass` Duplicated/contradictory requirements reconciled and called out explicitly: PRD 2 has 5 reconciliation notes (§7), PRD 3 has 5 reconciliation notes (§8), PRD 4 has 3 reconciliation notes (§9) — covering author hardcoding, company scope, embedding provider, parsing approach, chunking strategy, reranking, hybrid retrieval, decision memo scope, evaluation scope.
- `pass` Each PRD is implementation-ready: clear scope, contracts, acceptance criteria, verification approach: Each PRD has: Problem Statement (§1), System Boundaries with in/out scope (§2), Architecture (§3), Data Model (§4), API Contracts (§5), Quality Requirements (§6-7), Acceptance Criteria (§8-10), Verification Plan (§9-11).
- `pass` Deferred items captured explicitly and do not pollute near-term architecture: PRD 2 §12 (7 deferred items), PRD 3 §13 (9 deferred items), PRD 4 §14 (8 deferred items) — each with source and reason for deferral.
- `pass` Existing PRD files are not deleted: git status shows only new untracked files; PRD-Module-2-Investment-Intelligence-RAG.md, PRD-module-2.1-intelligence-retrieval.md, PRD-Platform-Intelligence-Strategy.md all verified present.
- `pass` Changes are docs-only; no application code behavior changes: Only 3 new .md files and 1 updated task .md file. No changes to api/, web/, config/, migrations/, or any code file.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-144-prd-consolidation-ingestion-retrieval-eval`.
<!-- MACHINE_RENDERED_END -->
