# PRD — Module 2: Thinker Intelligence RAG and Reasoning Framework

## 0. Product Intent

Build a local-first thinker-intelligence system that ingests writings from selected authors, stores a searchable knowledge base in `pgvector`, and powers a CapitalOS reasoning framework for investment and business judgment.

This module does **not** create digital twins of authors and does **not** use a single blended “wise finance agent.”  
Instead, it preserves distinct reasoning lenses from different authors, then synthesizes and critiques them explicitly.

It is an auditable decision-intelligence system that combines:

1. grounded knowledge retrieval (RAG)
2. structured multi-perspective reasoning
3. explicit synthesis while preserving differences
4. uncertainty handling

---

## 1. Goals

- Ingest and structure writings from configurable thinkers.
- Support URL-based ingestion with manual fallback.
- Store chunks, embeddings, metadata, and lineage in Postgres + `pgvector`.
- Provide grounded retrieval with citations.
- Support query-driven author selection and author-specific reasoning lenses at inference time.
- Support a synthesis layer that compares and reconciles lenses.
- Support a critic layer that checks for unsupported claims, false coherence, and flattened disagreement.
- Expose a company analysis mode that uses thinker lenses over retrieved evidence.

---

## 2. Non-Goals (v1)

- Fine-tuning custom model weights.
- Roleplaying an author as if the model “is” Buffett, Munger, or Marks.
- Autonomous trading or execution.
- Real-time market news streaming.
- Replacing structured personal-finance APIs with RAG.
- Building the full company-intelligence ingestion stack in this module.

Note:
- Personal financial questions like “how many GOOGL shares do I hold?” belong to structured data layers outside Module 2.
- Module 2 can consume company evidence for analysis, but the dedicated company-intelligence corpus is a later module.

---

## 3. Why This Design

### 3.1 Why a single blended agent is weaker

A single agent that has “read everything” tends to fail in predictable ways:

- voice collapse into generic finance-sounding wisdom
- source ambiguity
- false coherence
- loss of productive disagreement between thinkers

Examples of distinctions worth preserving:

- Buffett:
  business quality, moat, management, capital allocation, durable earnings power
- Marks:
  cycles, psychology, risk asymmetry, second-level thinking
- Mauboussin:
  base rates, expected value, competitive interaction, skill vs luck
- Munger:
  incentives, inversion, multidisciplinary models, misjudgment, opportunity cost

If these are blended too early, the system becomes smoother and weaker.

The same principle applies beyond investors:

- operators like Bezos, Grove, Horowitz, and Thompson should contribute operator-oriented lenses
- later domains like health, character, or stoicism should use the same architecture rather than a separate ad hoc system

### 3.2 Why digital twins are also insufficient

Running separate “author agents” is useful only if they are genuinely differentiated:

- distinct retrieval
- distinct evaluation criteria
- explicit comparison

Otherwise it becomes 5x cost for 5 paraphrases.

### 3.3 Preferred architecture

The preferred architecture is:

1. a shared knowledge layer
2. query-selected author-specific reasoning lenses
3. a synthesis layer
4. a critic layer

This preserves both efficiency and differentiation.

### 3.4 System Overview

This module has two layers.

Layer 1 — Knowledge layer:

- ingestion
- chunking
- embeddings
- retrieval

Layer 2 — Reasoning layer:

```text
Query
  ↓
Retrieval (shared corpus)
  ↓
Author Selection
  ↓
Author Lenses (parallel reasoning)
  ↓
Synthesis Agent
  ↓
Critic / Red Team
  ↓
Final Output
```


---

## 4. Core Requirements

## 4.1 Config-driven authors (no hardcoding)

- Authors must be loaded from config, not code constants.
- Config must support add/remove/disable without code changes.
- Suggested file: `config/rag_authors.yaml`

Example:

```yaml
authors:
  - id: warren_buffett
    name: Warren Buffett
    enabled: true
    domains: [investing, business]
    expertise_tags: [business_quality, moat, capital_allocation, valuation]
    overall_weight: 4.5
    role_type: investor

    reasoning_lens:
      focus:
        - business quality
        - moat durability
        - capital allocation
        - management integrity
      avoid:
        - macro speculation
      biases:
        - prefers predictability
        - prefers simplicity

  - id: howard_marks
    name: Howard Marks
    enabled: true
    domains: [investing, business]
    expertise_tags: [risk, cycles, psychology, second_level_thinking]
    overall_weight: 4.0
    role_type: investor

    reasoning_lens:
      focus:
        - cycles
        - risk asymmetry
        - market psychology
        - second level thinking

  - id: jeff_bezos
    name: Jeff Bezos
    enabled: true
    domains: [business, operator, strategy]
    expertise_tags: [customer_obsession, long_term_thinking, innovation, operating_leverage]
    overall_weight: 3.0
    role_type: operator
```

Selection rules:

- no author is hardcoded as mandatory
- no author gets a permanent pedestal
- authors are invoked based on query relevance, domain fit, expertise tags, corpus evidence quality, and configured weight
- weight is a ranking input, not an override that forces inclusion regardless of query fit
- the system may return 2 lenses for one query and 5 for another, depending on relevance
- future domains such as health, character, or stoicism should reuse the same author profile model

## 4.2 URL ingestion with manual fallback

- Primary flow: submit URL, system downloads and parses automatically.
- Fallback flow: paste cleaned text manually when automatic retrieval fails.
- Both flows normalize into the same document pipeline.

Supported source types in v1:
- HTML article/blog
- PDF
- plain text

## 4.3 Vector storage

- Use Postgres + `pgvector`
- Store:
  - chunk text
  - embeddings
  - author metadata
  - topic/concept tags
  - ingestion lineage
  - source cleanliness/confidence metadata

## 4.4 Citations and traceability

- Every non-trivial answer must cite supporting passages.
- Citations must include enough metadata to verify source grounding.
- The system must make it obvious which author/lens produced which reasoning.

## 4.5 Company analysis mode

Module 2 must support a company analysis mode, but in this module it means:

- retrieving thinker passages relevant to company analysis
- applying thinker lenses to a target company/problem
- returning a structured comparison

This mode may later consume inputs from a dedicated company-intelligence corpus, but the reasoning framework is defined here.

---

## 5. Example Author Set

Initial seed candidates:

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

Operator/strategy candidates:

- Jeff Bezos
- Andy Grove
- Ben Horowitz

Potential later expansion by use case:

- broader life/decision voices:
  Morgan Housel, Kahneman, Tetlock, Viktor Frankl
- later thematic domains:
  health, character building, stoicism, decision-making under stress

---

## 6. Corpus Design

## 6.1 Source library

Typical source types:

- annual letters
- investor memos
- speeches
- interviews
- essays
- transcripts
- research papers

Examples:

- Berkshire letters
- Buffett meeting transcripts
- Munger speeches/interviews
- Howard Marks memos
- Mauboussin papers
- Stratechery essays

## 6.2 Chunk metadata

Each chunk should store:

- `author`
- `work_title`
- `source_url`
- `published_at`
- `source_type`
- `topic_tags`
- `concept_tags`
- `cleanliness/confidence`
- `doc_hash`
- `chunk_index`

Concept tags should include things like:

- valuation
- moat
- incentives
- capital allocation
- cycles
- risk
- psychology
- base rates
- competition
- management
- culture
- opportunity cost

---

## 7. Reasoning Architecture

## 7.1 Layer 1 — Shared knowledge layer

This is the common retrieval substrate:

- thinker corpus in `pgvector`
- metadata filters by author/topic/date
- semantic retrieval
- optional metadata boosts

This layer is shared; the differentiation happens after retrieval.

## 7.2 Layer 2 — Retrieval

Retrieval should support both:

- semantic retrieval
- metadata filtering

Required retrieval features:

- author filtering
- topic/concept filtering
- date filtering
- quality/confidence filtering
- optional per-author balancing to stop prolific authors from dominating

Important:
- for broad questions, retrieval must work by concept, not only keyword

## 7.3 Layer 3 — Author selection

Before lens execution, the system should determine which authors to invoke.

Selection should be query-driven, not hardcoded.

Inputs to selection:

- query topic and intent
- requested domain (`investing`, `business`, `operator`, later `health`, `character`, etc.)
- author `expertise_tags`
- author `role_type`
- author `overall_weight`
- author corpus quality and retrieval strength
- available supporting evidence for that author on the current query

Selection output:

- ranked author set for this query
- reason each selected author was chosen
- authors considered but not selected, if useful for debugging/audit

Selection principles:

- no permanent “core four” authors
- high-weight authors should still be excluded if they are weakly relevant
- low-weight authors may still be included when the query strongly matches their expertise
- operator questions should often prefer operator voices over pure investors
- future non-investment topics should select from their own author pools by the same mechanism

## 7.4 Layer 4 — Author-lens adapters

This is the heart of Module 2.

Separate inference calls should be made using distinct author reasoning cards selected at query time.

Each author card should be configuration-driven and should include:

- domain fit
- role type
- focus areas
- avoid patterns
- known biases or preferences
- output schema expectations

Illustrative examples:

- Buffett:
  business quality, moat, management, capital allocation, durable earnings power
- Marks:
  cycles, psychology, risk asymmetry, second-level thinking
- Mauboussin:
  base rates, expected value, competitive interaction, distribution of outcomes
- Munger:
  inversion, incentives, multidisciplinary models, avoiding stupidity
- Bezos:
  customer obsession, long-term orientation, operational flywheels, invention
- Grove:
  strategic inflection points, competition, paranoia, execution discipline
- Horowitz:
  operator tradeoffs, leadership under stress, hard decisions in messy realities
- Thompson:
  aggregation, internet economics, distribution, strategic power

The system must allow additional cards entirely from config, without code-level special casing for any author family.

## 7.5 Layer 5 — Synthesis agent

The synthesis layer must not merely “combine.”

It must explicitly output:

- common ground
- major disagreements
- what each lens may be missing
- decision-relevant variables
- missing information
- highest-risk assumptions
- tentative conclusion
- confidence level

This prevents smooth nonsense.

## 7.6 Layer 6 — Critic / red team

The critic layer must explicitly ask:

- did synthesis flatten meaningful disagreement?
- did any lens rely on unsupported claims?
- are citations actually supportive?
- which claim is least grounded?
- what is the strongest counterargument?
- what would break this conclusion?

This is a first-class stage, not an optional flourish.

---

## 8. User Experience

## 8.1 Author and source management

- Add/edit authors via config-backed API/UI
- Manage author profiles, expertise tags, role types, and weights
- Add sources by URL
- Manual text paste fallback
- Trigger ingest/re-ingest
- View ingestion status and errors
- View chunk counts and document metadata

## 8.2 Knowledge query mode

User asks a question and receives:

- direct answer
- cited passages
- selected lens-specific sections
- synthesis section
- critic section

## 8.3 Company analysis mode

Input:
- company name/ticker
- optional question or thesis framing

Output:

- query-selected thinker/operator lens analysis by author
- common ground
- disagreements
- what is missing
- tentative conclusion
- citations

Example output sections:

- Buffett view
- Marks view
- Mauboussin view
- Munger view
- synthesis
- critic

These are illustrative only. The actual returned lenses should depend on query-time author selection.

---

## 9. System Pipeline

## 9.1 Ingestion pipeline

1. source registration (`author_id`, URL, tags)
2. fetch content
3. parse into normalized text
4. clean and annotate metadata
5. chunk text
6. generate embeddings
7. store chunks in Postgres + `pgvector`
8. record ingestion job status and lineage

## 9.2 Query pipeline

1. accept query
2. determine query domain, topic, and likely author set
3. retrieve relevant chunks
4. select authors based on relevance, expertise, evidence quality, and weight
5. run author-lens adapters
6. run synthesis
7. run critic
8. return structured answer with citations and selected-author metadata

---

## 10. Data Model (High Level)

- `rag_authors`
  - `id`, `name`, `enabled`, `domains`, `expertise_tags`, `overall_weight`, `role_type`, `config_source`
- `rag_author_cards`
  - `author_id`, `focus_areas`, `avoid_patterns`, `biases`, `prompt_adapter`, `enabled`
- `rag_sources`
  - `id`, `author_id`, `url`, `source_type`, `status`, `hash`, `last_ingested_at`
- `rag_documents`
  - `id`, `source_id`, `title`, `published_at`, `raw_text`, `clean_text`
- `rag_chunks`
  - `id`, `document_id`, `chunk_index`, `text`, `token_count`, `metadata_json`
- `rag_embeddings`
  - `chunk_id`, `embedding vector`
- `rag_ingestion_jobs`
  - `id`, `source_id`, `status`, `error`, `stats_json`, `started_at`, `finished_at`
- `rag_queries`
  - `id`, `question`, `response`, `model`, `created_at`
- `rag_query_selected_authors`
  - `query_id`, `author_id`, `selection_reason`, `selection_score`
- `rag_query_evidence`
  - `query_id`, `chunk_id`, `author_id`, `retrieval_rank`, `retrieval_score`
- `rag_query_lens_outputs`
  - `query_id`, `author_id`, `output_json`
- `rag_query_syntheses`
  - `query_id`, `output_json`
- `rag_query_critiques`
  - `query_id`, `output_json`

---

## 11. API Surface (v1)

### Catalog and config

- `GET /rag/authors`
- `POST /rag/authors/sync-config`
- `GET /rag/sources`
- `POST /rag/sources`

### Ingestion

- `POST /rag/ingest/url`
- `POST /rag/ingest/manual`
- `POST /rag/ingest/retry/{source_id}`
- `GET /rag/ingest/jobs`

### Query and analysis

- `POST /rag/query`
- `POST /rag/analyze/company`
- `GET /rag/documents/{id}`
- `GET /rag/queries/{id}`

Possible response shape for analysis:

- `evidence`
- `selected_authors`
- `lens_outputs`
- `synthesis`
- `critic`
- `citations`

---

## 12. Reliability and Cost Controls

- idempotent ingestion via content hash
- deduplicate near-identical chunks
- chunk/token limits per source
- embedding batching with retry/backoff
- retrieval limits and author balancing
- lower-cost retrieval/filtering model where appropriate
- stronger model for synthesis/critic only when needed

Cost principle:
- do not pay for unnecessary lens calls
- select only the authors justified by the query and evidence
- use weights to improve prioritization, not to force prestige-based invocation

---

## 13. Security and Compliance

- respect robots/TOS for automated downloads
- store source URL and ingestion timestamp
- local-first by default
- support source disable/delete
- preserve provenance so source material can be audited or removed

---

## 14. Success Criteria (v1)

Module 2 is successful when:

- new authors can be added via config without code edits
- URL ingestion works for common HTML/PDF/text cases
- manual fallback works for failures
- answers are source-cited
- selected lens outputs are visibly differentiated
- synthesis preserves disagreement rather than flattening it
- critic catches unsupported or weakly grounded conclusions
- company analysis mode is useful and traceable
- author selection is relevance-driven and not hardcoded to a fixed elite set

---

## 15. Evaluation Framework

Module 2 should not be evaluated informally. It needs an explicit evaluation harness so quality can be measured over time as authors, prompts, models, and retrieval settings change.

## 15.1 Core evaluation dimensions

### Answer quality

Measures whether the final output is actually useful for the user’s question.

Score dimensions:

- relevance to the question asked
- completeness relative to the task
- clarity and structure
- actionability / decision usefulness
- uncertainty calibration

Suggested metric:
- `answer_quality_score`

### Citation faithfulness

Measures whether important claims are actually supported by cited passages.

Score dimensions:

- citation coverage for material claims
- support strength of cited passages
- absence of unsupported synthesis
- absence of citation laundering

Suggested metric:
- `citation_faithfulness_score`

### Lens differentiation

Measures whether lens outputs are genuinely distinct or merely paraphrases.

Score dimensions:

- distinct focus areas across lenses
- distinct concerns raised
- distinct decision variables
- low semantic overlap between lens outputs

Suggested metric:
- `lens_differentiation_score`

### Critic usefulness

Measures whether the critic meaningfully improves the output instead of restating it.

Score dimensions:

- whether the critic identifies unsupported claims
- whether it catches flattened disagreement
- whether it raises a meaningful counterargument
- whether critique materially changes the synthesis or final answer

Suggested metric:
- `critic_usefulness_score`

### Overall decision usefulness

Measures whether the end-to-end response helps a user think better or act better.

Suggested metric:
- `overall_decision_usefulness_score`

## 15.2 Evaluation dataset

Maintain a fixed eval set of prompts, expanded over time.

Prompt categories:

- company analysis prompts
- thinker comparison prompts
- operator/business strategy prompts
- portfolio judgment prompts once cross-layer integration exists
- later, non-investment domain prompts

Each eval case should store:

- prompt text
- intended query type / domain
- expected useful answer characteristics
- expected relevant authors or author types
- expected citation behavior
- expected disagreements or counterarguments where applicable

## 15.3 Evaluation artifacts to log

For each eval run, store:

- selected authors
- author selection reasons
- retrieved chunks
- lens outputs
- synthesis output
- critic output
- final answer
- citations used
- model and retrieval configuration

This makes regressions diagnosable instead of anecdotal.

## 15.4 Human evaluation

Human review is required for the highest-value dimensions.

Use a small rubric per eval case:

- 1-5 or pass/fail for answer quality
- 1-5 or pass/fail for citation faithfulness
- 1-5 or pass/fail for lens differentiation
- 1-5 or pass/fail for critic usefulness

Human review should be done on a recurring sample even if automated checks exist.

## 15.5 Automated evaluation

Automated checks should be used where they are reliable.

Examples:

- claim-to-citation coverage checks
- overlap/similarity checks between lens outputs
- selected-author relevance checks against expected author/domain profile
- citation presence and metadata integrity checks
- critic detection rate for known injected weak-claim test cases

Important:
- automated checks support evaluation
- they do not replace human judgment for subtle reasoning quality

## 15.6 Regression tracking

Track evaluation scores over time by:

- retrieval configuration version
- prompt template version
- model version
- author registry version

This allows comparison after:

- adding new authors
- changing lens prompts
- changing retrieval ranking
- changing synthesis/critic prompts

## 15.7 Minimum acceptance bar

Before broader rollout, Module 2 should meet a minimum quality bar on the eval set:

- answers are consistently useful and relevant
- citations support major claims
- lens outputs remain differentiated
- critic output catches meaningful weaknesses
- no major regressions after adding authors or changing prompts

---

## 16. Phased Delivery Plan

### Phase 1 — Foundation

- config-driven authors
- URL/manual ingestion
- `pgvector` schema
- chunk metadata and lineage
- semantic query with citations

### Phase 2 — Lens Framework

- author reasoning cards
- author profile registry with expertise tags, role types, and weights
- query-time author selection
- lens-specific inference flow
- structured lens outputs

### Phase 3 — Synthesis and Critic

- synthesis output schema
- critic/red-team output schema
- traceability from answer back to supporting chunks

### Phase 4 — Company Analysis Mode

- company-focused prompts
- thinker-lens comparison for target company
- better concept tagging and retrieval balancing

---

## 17. Relationship To The Broader Platform

Module 2 is not the whole intelligence system.

It provides:

- thinker corpus
- author-lens reasoning
- synthesis
- critic

It does not replace:

- structured personal finance querying
- dedicated company-intelligence ingestion
- portfolio/company combined judgment workflows

Those belong to the broader platform strategy documented separately.
