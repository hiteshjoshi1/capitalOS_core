# Issue 165: RAG docs consolidation and PRD refresh

## Objective
- Bring the RAG docs and PRDs up to the current architecture after the upcoming pipeline updates.
- Reduce document sprawl and establish one single-source-of-truth document per major area.
- Focus on architecture, design choices, and tradeoffs, not code-level walkthroughs.

## Problem
- Current RAG docs overlap and disagree.
- Some architecture docs are stale relative to the codebase.
- PRD-2, PRD-3, and PRD-4 no longer cleanly match the system being built.

## Architecture Decisions
- Each major area should have one canonical architecture/design document.
- Historical notes can remain, but only one current document should be the source of truth.
- PRDs should describe the actual target architecture and design choices, not an outdated plan.

## Required Outputs
Create or consolidate a single canonical document for each of:
1. Ingestion
2. Retrieval
3. Evaluations
4. AI Sage user experience
5. AI Authors / Author Library user experience

Also update and move the following into `docs/` as current product/architecture references:
- `PRD-2-Ingestion`
- `PRD-3-Retrieval`
- `PRD-4-Eval`

## Content Requirements
Each canonical doc should answer:
- what are we doing
- why are we doing it
- how does the architecture work
- what key design choices were made
- what alternatives were considered briefly
- why this architecture was chosen versus those alternatives

Avoid:
- code-level implementation detail
- duplicate docs that say the same thing

## Acceptance Criteria
- [ ] There is exactly one canonical current-state / target-state doc for each of the five areas listed above.
- [ ] PRD-2, PRD-3, and PRD-4 are refreshed to match the architecture actually being built.
- [ ] The refreshed PRDs live in `docs/`.
- [ ] Stale/overlapping RAG docs are either consolidated or clearly marked non-canonical.
- [ ] The resulting docs describe architecture and design choices, not code walkthroughs.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

