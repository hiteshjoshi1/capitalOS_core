# Issue 151: Charlie Munger canonical corpus ingestion

## Objective
- Build a high-fidelity Charlie Munger corpus that favors canonical source quality, section-level document boundaries, and clean authorship attribution.
- Use the Stripe Press Poor Charlie's Almanack omnibus page as the primary canonical raw source for PCA content, but never ingest it as one giant document.
- Add the remaining Munger corpus in separate collections using cleaner individual Wesco, DJCO, and late-interview sources.

## Architecture Decisions
- Decision 1: Use `https://www.stripe.press/poor-charlies-almanack/book?progress=0.00%25` as the primary canonical raw source for Poor Charlie's Almanack content because the full book text is present in server-rendered HTML and exposes clear section/talk boundaries.
- Decision 2: Do not persist the Stripe omnibus as a single logical document. Parse it by section headings and create one logical document per intellectual work using the Stripe URL as the shared `source_url`.
- Decision 3: Treat the Stripe PCA talks as the canonical version of classic Munger talks. WorldlyPartners duplicate PDFs are fallback-only for validation, metadata verification, or use when Stripe extraction fails.
- Decision 4: Do not include Wesco meeting notes in this issue. The current Wesco PDFs are note-taker mediated and require additional Charlie-only filtering/selection work that should be handled separately.
- Decision 5: Use DJCO transcripts/notes as the primary source for `munger_djco_notes`.
- Decision 6: Use WorldlyPartners and other stable transcript/PDF sources as the primary source for post-Almanack and late-period interviews in `munger_late_interviews`.
- Decision 7: Do not ingest these Stripe omnibus sections into Charlie's corpus: `Foreword: Collison on Munger`, both `Rebuttal by Charles T. Munger` sections, `Introduction by Peter D. Kaufman`, Chapter One biography, Chapter Two family memories, and `Acknowledgments`.
- Decision 8: Ingest `Foreword: Buffett on Munger`, but attribute it to Warren Buffett, not Charlie Munger.
- Decision 9: Ingest Chapter Three (`The Munger Approach to Life, Learning, and Decision-Making`) as a separate non-speech Charlie corpus document with lower retrieval weight than the talks.
- Decision 10: Ingest `Recommended reading` as a separate Charlie document because it is corpus-relevant reference material, but weight it below canonical talks.
- Decision 11: For `Talk X Revisited`, prefer Option B: store each revisited section as a separate document with metadata linking it to the parent talk. If the current schema cannot support parent linkage cleanly, append the revisited section to the corresponding talk as a fallback and document that limitation explicitly.
- Decision 12: Create and persist ingestion metadata derived from section parsing, including `canonical_work_id`, `collection`, `canonical_status`, `dedupe_priority`, `source_section`, and any parent/child linkage used for revisited sections.
- Decision 13: Retrieval weighting should reflect source quality: Stripe PCA talks `1.00`, Stripe Chapter Three synthesis `0.85`, late interviews `0.82`, DJCO notes/transcripts `0.74`. WorldlyPartners duplicate classic talks and Valueplays should not be retrieved as primary material unless a fallback path is explicitly invoked.
- Decision 14: The eleven PCA talks should be ingested from the single Stripe omnibus `book` URL using deterministic same-page boundaries, not by visiting the broken standalone Stripe talk pages. The implementation should treat the omnibus as one raw source that fans out into many logical documents.
- Decision 15: For implementation purposes, talk boundaries in the omnibus should be modeled as: Talk One = `Talk One` until `Talk Two`; Talk Two = `Talk Two` until `Talk Three`; Talk Three = `Talk Three` until `Talk Four`; and so on through Talk Eleven. This keeps the core talk material on the canonical Stripe source while allowing revisited/Q&A material to either remain inside the talk bundle or split into child docs.
- Decision 16: Execution must be phased. Stripe validation comes first, Stripe insertion comes second, DJCO validation/insertion comes third, and late-interview validation/insertion comes fourth. The implementation should not bulk-ingest all sources in one blind pass.
- Decision 17: Validation must be artifact-based before insertion. For each Stripe talk, and then for each non-Stripe source, produce a concrete review artifact or equivalent logged evidence showing extracted text length, included sections, metadata, and enough content preview to confirm that the extraction is real and not heading-only noise.
- Decision 18: Stop rule: if a source or section validates poorly, do not ingest it. Record the failure, mark it skipped or fallback-needed, and continue only with sources that passed validation.

## Execution Phases
- Phase 1: Validate all 11 Stripe omnibus talk boundaries from the single `book` URL.
  - For each talk, extract by same-page boundary `Talk N -> before Talk N+1`.
  - Produce a review artifact with:
    - proposed metadata
    - included parser section list
    - extracted text length
    - content preview or full extracted text
  - Pass only if:
    - the extraction contains real body text
    - the title/venue/date at the top look correct
    - the section does not bleed into the next talk
    - the result is not just heading/table-of-contents noise
- Phase 2: Ingest only the Stripe talks that passed Phase 1 and verify DB state.
  - Confirm one logical document per intended canonical work or documented fallback bundle.
  - Confirm metadata persistence, non-trivial `clean_text`, and created chunks.
  - Confirm rejected/failed sections are not silently inserted as junk.
- Phase 3: Validate and ingest DJCO documents.
  - Sample each listed DJCO source first.
  - Trim only boilerplate/site-header noise where needed.
  - Ingest only after the extracted body is confirmed to be mostly Charlie Q&A/transcript content.
- Phase 4: Validate and ingest late interviews.
  - Sample each listed interview/transcript first.
  - Trim only title-page/editorial boilerplate where needed.
  - Ingest only after the extracted body is confirmed to be mostly direct Charlie conversation/talk content.
- Stop condition:
  - Any source that extracts poorly should be documented and skipped rather than force-ingested.

## Acceptance Criteria
- [ ] A documented ingestion workflow exists for Charlie Munger that follows this source hierarchy:
- [ ] `1.` Stripe omnibus parsed section-by-section for `munger_pca_talks`
- [ ] `2.` WorldlyPartners individual PDFs as fallback/verification and as primary for post-Almanack interviews
- [ ] `3.` DJCO transcripts/notes as primary for `munger_djco_notes`
- [ ] `4.` Valueplays omnibus marked audit/fallback only
- [ ] The Stripe omnibus is parsed into multiple logical documents rather than one monolithic document.
- [ ] The Stripe omnibus ingestion plan explicitly excludes `Collison foreword`, both `Munger rebuttals`, `Kaufman introduction`, Chapter One biography, Chapter Two family memories, and `Acknowledgments`.
- [ ] The Stripe omnibus ingestion plan ingests `Foreword: Buffett on Munger` under author `warren_buffett`.
- [ ] The Stripe omnibus ingestion plan ingests Chapter Three as a separate Charlie document.
- [ ] The Stripe omnibus ingestion plan ingests `Recommended reading` as a separate Charlie document.
- [ ] The Stripe omnibus ingestion plan ingests each of the eleven talks as separate logical documents with the following canonical work IDs and titles:
- [ ] `munger_1986_harvard_school_commencement` — `Harvard School Commencement Speech`
- [ ] `munger_1994_usc_worldly_wisdom` — `A Lesson on Elementary, Worldly Wisdom`
- [ ] `munger_1994_worldly_wisdom_qna` — `Worldly Wisdom, Updated: Q&A with Charlie`
- [ ] `munger_1996_stanford_worldly_wisdom_revisited` — `A Lesson on Elementary, Worldly Wisdom, Revisited`
- [ ] `munger_practical_thought` — `Practical Thought about Practical Thought?`
- [ ] `munger_1998_harvard_law_reunion` — `Harvard Law School 50th Reunion Address`
- [ ] `munger_1998_charitable_foundations` — `Investment Practices of Leading Charitable Foundations`
- [ ] `munger_2000_philanthropy_roundtable` — `Philanthropy Roundtable`
- [ ] `munger_great_financial_scandal_2003` — `The Great Financial Scandal of 2003`
- [ ] `munger_2003_academic_economics` — `Academic Economics`
- [ ] `munger_2007_usc_gould_commencement` — `USC Gould School of Law Commencement Address`
- [ ] `munger_psychology_human_misjudgment_pca` — `The Psychology of Human Misjudgment`
- [ ] The eleven PCA talks are ingested from the single Stripe omnibus `book` URL, not from the individual Stripe talk pages.
- [ ] The implementation uses deterministic same-page talk boundaries from the omnibus so that Talk Two ends where Talk Three begins, Talk Three ends where Talk Four begins, and so on.
- [ ] The issue preserves the current non-omnibus sources as-is: Wesco PDFs, DJCO notes/transcripts, and late-interview PDFs/transcripts remain separate source inputs and are not reworked away from their listed URLs.
- [ ] Execution is phased rather than all-at-once:
- [ ] Phase 1 validates all 11 Stripe talks before any Stripe insertion happens.
- [ ] Phase 2 inserts only Stripe talks that passed validation and verifies DB rows/chunks/metadata after insertion.
- [ ] Phase 3 validates and then ingests DJCO sources.
- [ ] Phase 4 validates and then ingests late-interview sources.
- [ ] Any source that validates poorly is skipped and recorded rather than force-ingested.
- [ ] `The Psychology of Human Misjudgment` from the Stripe omnibus is treated as the canonical PCA version.
- [ ] `Worldly Wisdom, Updated: Q&A with Charlie` is ingested as a separate Q&A document, not merged into Talk Two.
- [ ] `Talk X Revisited` sections are stored as separate documents linked to their parent talk if the schema supports it; otherwise they are appended to the parent talk and the fallback is documented in code/tests/task notes.
- [ ] The ingestion implementation creates or persists metadata equivalent to:
- [ ] `collection`
- [ ] `source_type`
- [ ] `speaker`
- [ ] `canonical_work_id`
- [ ] `canonical_status`
- [ ] `dedupe_priority`
- [ ] `source_section`
- [ ] `source_publisher`
- [ ] `note_taker` where applicable for meeting notes
- [ ] `parent_work_id` or equivalent linkage if revisited sections are separate documents
- [ ] The implementation supports or documents one-record-per-intellectual-work behavior for Stripe PCA sections even though they share the same raw `source_url`.
- [ ] The implementation or task notes document the verified omnibus talk-section mapping for at least these live-checked cases:
- [ ] Talk Two uses the omnibus boundary `Talk Two -> before Talk Three`
- [ ] Talk Three uses the omnibus boundary `Talk Three -> before Talk Four`
- [ ] A concrete validation artifact or equivalent logged evidence exists for every Stripe talk before insertion, showing extracted text and proposed metadata.
- [ ] A concrete validation artifact or equivalent logged evidence exists for each DJCO and late-interview source before insertion, showing that the extracted content is real and mostly Charlie material.
- [ ] The ingestion plan includes `munger_djco_notes` using the listed 2013-2023 Daily Journal annual meeting notes/transcripts and the 2017 post-annual-meeting fireside chat as separate documents.
- [ ] The ingestion plan includes `munger_late_interviews` using the listed 2017 Michigan Ross, 2020 Caltech, 2020 University of Redlands, 2022 Singleton Prize, and optional 2023 Acquired transcript sources.
- [ ] WorldlyPartners duplicate classic-talk PDFs are not ingested as primary canonical duplicates when the Stripe PCA extraction succeeded.
- [ ] Valueplays is marked audit/fallback only and is not ingested as the default primary source.
- [ ] The final ingestion behavior prevents naive corpus pollution from mixed Stripe sections and preserves author fidelity for Charlie vs Buffett vs editors.
- [ ] Retrieval-facing metadata or weighting fields exist, or a documented deterministic weighting mechanism exists, implementing the requested source-specific priority hierarchy.
- [ ] Tests cover Stripe section parsing, canonical work creation, author attribution for Buffett's foreword, omission of excluded sections, late-interview/Wesco/DJCO collection metadata, and fallback behavior when Stripe extraction fails.
- [ ] The implementation is verifiable via Makefile commands and curl-verifiable ingestion flows.

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
  - `Can revisited sections be modeled as separate documents with parent linkage using the current schema, or is a schema extension required?`
  - `Should source-specific retrieval weighting be persisted as metadata or implemented in ranking logic only?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._
