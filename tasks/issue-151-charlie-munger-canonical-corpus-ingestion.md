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
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `completed`
- Workflow Status: `completed`
- Provider/Model: `gpt-5.4`
- Last Updated: `2026-04-25`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` — `make lint`
- `typecheck`: `pass` — `make typecheck`
- `tests`: `pass` — `make contract-backend && make test-backend && make contract-frontend && make test-frontend && make orch-test`
- `e2e`: `pass` — `make e2e`
- `api-smoke`: `pass` — `make api-smoke`
- `policy-checks`: `pass` — `Charlie Munger Stripe validation endpoint + preset-driven phase workflow + metadata weighting added`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `docs/rag-ingestion.md` — reason: Charlie workflow requires curl-verifiable phased validation/insertion documentation.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `none`
- Attempted mitigations:
  - `n/a`
  - `n/a`
- Suggested human action: `none`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `curl POST /rag/authors/charlie_munger/discover -> POST /rag/ingest/validate -> POST /rag/ingest/url`
- Open questions:
  - `none`
  - `none`
- If PR raised but intent partial:
  - unmet criteria: `none`
  - follow-up issue: `none`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented a Charlie Munger canonical-corpus ingestion workflow with URL-based source presets, Stripe omnibus section fanout, validation-before-insert support, phased/curl-verifiable docs, and regression coverage. The final required Makefile verification suite passed on the current tree.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Charlie Munger ingestion follows the requested source hierarchy with Stripe omnibus as canonical PCA input, DJCO as primary meeting-note corpus, late interviews as separate sources, and fallback-only guidance for duplicate classic-talk sources.
- Acceptance criterion: Stripe omnibus content is parsed into multiple logical documents with explicit exclusions, Buffett foreword author override, Chapter Three and Recommended Reading support, and separate logical talk/Q&A/revisited handling.
- Acceptance criterion: Execution is phased and validation-first, with concrete validation artifacts available before insertion and failed sources skipped rather than force-ingested.
- Acceptance criterion: Retrieval-facing metadata includes canonical work identifiers, canonical/fallback status, dedupe priority, collection/source metadata, and parent linkage for companion sections.
- Acceptance criterion: Tests cover Stripe section parsing behavior, Charlie preset registration/discovery, author fidelity, exclusion behavior, and validation preview behavior.
- Acceptance criterion: The workflow is documented and verifiable with Makefile targets and curl-based ingestion endpoints.

## Prepare
Checked out `feature/issue-151-charlie-munger-canonical-corpus-ingestion` from `main` and ensured task file exists.

## Plan Summary
Extend the existing RAG ingestion pipeline instead of building a parallel path: add Charlie-specific source presets and discovery seeds, normalize Stripe omnibus parsing quirks, expose a validation-only preview endpoint that emits review artifacts before insertion, persist retrieval-facing metadata for canonical/companion/fallback handling, document the phased workflow, and cover the new behavior with backend tests.

### Architecture Decisions
- Encoded Charlie-specific ingestion behavior in a dedicated preset module so discovery, manual source registration, and ingestion share the same deterministic source rules.
- Kept Stripe omnibus ingestion as one raw source URL that fans out into multiple logical documents, rather than persisting one monolithic omnibus document.
- Added a validation-only ingestion preview flow so Stripe, DJCO, and late-interview sources can be reviewed and skipped before any DB insertion.
- Used source-specific Stripe normalization to split embedded omnibus sections such as revisited talks into stable logical sections before selector fanout.
- Persisted retrieval-facing metadata and weights in logical-document metadata instead of hardcoding ranking behavior elsewhere.

### Acceptance Criteria
- Charlie Munger ingestion follows the requested source hierarchy with Stripe omnibus as canonical PCA input, DJCO as primary meeting-note corpus, late interviews as separate sources, and fallback-only guidance for duplicate classic-talk sources.
- Stripe omnibus content is parsed into multiple logical documents with explicit exclusions, Buffett foreword author override, Chapter Three and Recommended Reading support, and separate logical talk/Q&A/revisited handling.
- Execution is phased and validation-first, with concrete validation artifacts available before insertion and failed sources skipped rather than force-ingested.
- Retrieval-facing metadata includes canonical work identifiers, canonical/fallback status, dedupe priority, collection/source metadata, and parent linkage for companion sections.
- Tests cover Stripe section parsing behavior, Charlie preset registration/discovery, author fidelity, exclusion behavior, and validation preview behavior.
- The workflow is documented and verifiable with Makefile targets and curl-based ingestion endpoints.

### Planned Paths
- `api/app/rag`
- `api/tests`
- `config/rag_authors.yaml`
- `docs/rag-ingestion.md`
- `tasks/issue-151-charlie-munger-canonical-corpus-ingestion.md`

## Build Summary
Implemented a Charlie Munger canonical-corpus ingestion workflow with URL-based source presets, Stripe omnibus section fanout, validation-before-insert support, phased/curl-verifiable docs, and regression coverage. The final required Makefile verification suite passed on the current tree.

### Changed Files
- `api/app/rag/discovery.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/rag/ingestion/selector.py`
- `api/app/rag/ingestion/source_presets.py`
- `api/app/routers/rag.py`
- `api/tests/test_munger_corpus_presets.py`
- `config/rag_authors.yaml`
- `docs/rag-ingestion.md`
- `tasks/issue-151-charlie-munger-canonical-corpus-ingestion.md`

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
Implemented a Charlie Munger canonical-corpus ingestion workflow with URL-based source presets, Stripe omnibus section fanout, validation-before-insert support, phased/curl-verifiable docs, and regression coverage. The final required Makefile verification suite passed on the current tree.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` Documented Charlie ingestion workflow follows the requested source hierarchy and keeps fallback-only sources out of the primary path.: `config/rag_authors.yaml` now seeds Stripe omnibus, DJCO, late interviews, and preserves Wesco separately; `docs/rag-ingestion.md` documents WorldlyPartners classic-talk PDFs and Valueplays as fallback/audit-only.
- `pass` Stripe omnibus is parsed into multiple logical documents instead of one monolithic document.: `api/app/rag/ingestion/source_presets.py` defines Stripe fanout documents by section boundaries and `api/app/rag/ingestion/pipeline.py` previews/persists logical documents per fanout entry.
- `pass` Stripe exclusions, Buffett foreword author attribution, Chapter Three, and Recommended Reading behavior are explicit.: Stripe preset config excludes the Collison foreword, both Munger rebuttals, Kaufman introduction, Chapter One, Chapter Two, and acknowledgments; it separately includes Buffett foreword with `speaker/author` override plus Chapter Three and Recommended Reading support.
- `pass` The eleven PCA talks come from the single Stripe omnibus with deterministic talk boundaries and separate Q&A/revisited handling.: The Stripe preset maps the canonical work IDs to omnibus heading windows, keeps `Worldly Wisdom, Updated: Q&A with Charlie` separate, and uses child linkage metadata for revisited documents where split sections are supported.
- `pass` Execution is phased and validation-first, with concrete artifacts before insertion and poor sources skipped.: `api/app/routers/rag.py` adds `/rag/ingest/validate`; `api/app/rag/ingestion/pipeline.py` builds `validation_artifacts` with metadata, section lists, extracted lengths, previews, and rejection details before persistence.
- `pass` Metadata and weighting fields exist for retrieval-facing prioritization and author/source fidelity.: Preset metadata populates `collection`, `source_type`, `speaker`, `canonical_work_id`, `canonical_status`, `dedupe_priority`, `source_section`, `source_publisher`, `note_taker`, and `parent_work_id`, along with deterministic retrieval weights by source class.
- `pass` DJCO and late-interview sources are included as separate collections without reworking away from their listed URLs, while Wesco remains separate.: `config/rag_authors.yaml` adds the listed 2013-2023 DJCO and late-interview sources, and the new preset tests assert the Charlie config still includes the Berkshire Wesco archive URL while leaving it unmodified by Charlie presets.
- `pass` Tests cover Stripe parsing/presets, author fidelity, exclusions, collection metadata, and validation preview behavior.: `api/tests/test_munger_corpus_presets.py` covers Stripe preset structure, Stripe normalization, Charlie source discovery/registration, config seeding, and validation preview behavior; the full backend suite also passed after these additions.
- `pass` The implementation is verifiable via Makefile commands and curl-verifiable ingestion flows.: `docs/rag-ingestion.md` now documents the phased `discover -> validate -> ingest` curl workflow, and the full required Makefile verification suite passed.

### Risk Flags
- external-source-layout-drift

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
