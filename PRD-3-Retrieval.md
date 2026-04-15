# PRD 3 — Retrieval: Query-Time Retrieval and Synthesis Stack

## 0. Document Purpose

This PRD defines the complete query-time retrieval and reasoning stack for CapitalOS intelligence — from user query through intent routing, evidence retrieval, reranking, author-lens reasoning, synthesis, and critique. It consolidates and reconciles requirements from PRD-Module-2, PRD-Module-2.1, PRD-Platform-Intelligence-Strategy, and issues 130, 131, 132, 133, 137, 138, 141, and 142.

**Lifecycle boundary:** PRD 3 begins where PRD 2 (Ingestion) ends. It assumes a populated corpus in Postgres + pgvector with full metadata. PRD 3 ends at answer delivery. Evaluation of retrieval quality and continuous improvement belong to PRD 4 (Eval).

---

## 1. Problem Statement and User Jobs

### Problem

A high-quality corpus is worthless without a retrieval and reasoning stack that can surface the right evidence, apply differentiated reasoning lenses, and produce answers that are materially better than generic AI chat. The system must understand user intent, retrieve precisely, rerank reliably, and synthesize with preserved disagreement — not produce smooth but shallow summaries.

### User Jobs

| Job | Description |
|-----|-------------|
| **Learn concepts deeply** | Ask "What makes a good business?" and receive differentiated author perspectives, synthesis, critique, and reading recommendations — not blended finance platitudes. |
| **Pressure-test a thesis** | Submit "I think Tencent Music is attractive because …" and receive structured pushback: missing questions, blind spots, real-world evidence, thesis strengths and weaknesses. |
| **Retrieve prior research** | Ask "Show me everything I know about TME" and get prior research notes, stored evidence, past conclusions, and key author references. |
| **Get precise answers** | Ask about a specific author's specific view and not get diluted multi-author noise. Ask about a specific year and get time-filtered results. |
| **Trust the evidence** | See exactly which passages support each claim, which author produced which reasoning, and what the system does not know. |

---

## 2. System Boundaries

### In Scope

- Pre-retrieval intent routing and query understanding
- Query decomposition for multi-part questions
- Hybrid retrieval: dense vector search (pgvector) + sparse keyword search (Postgres tsvector/tsquery)
- Reciprocal Rank Fusion (RRF) for combining dense and sparse results
- Cross-encoder reranking (dedicated reranker, not LLM-prompt-based)
- Context expansion around winning chunks
- Dynamic author selection based on query relevance, expertise, and corpus evidence
- Author-lens reasoning adapters (parallel per-author inference)
- Synthesis layer with explicit disagreement preservation
- Critic / red-team layer
- Three user-facing modes: Concept Mode, Company Thesis Mode, Research Memory Mode
- Query routing across data planes (structured finance DB vs. thinker corpus vs. company corpus)
- Citation and traceability for every non-trivial answer
- Research note save/retrieve functionality

### Out of Scope

- Corpus ingestion and embedding (PRD 2)
- Retrieval quality measurement and golden datasets (PRD 4)
- Autonomous trading or execution
- Digital-twin author roleplay
- Full decision memo workflows, outcome reviews, calibration records (deferred — see §13)
- Replacing structured personal-finance APIs with RAG
- Autonomous investment recommendations
- Portfolio-wide monitoring dashboards

---

## 3. Architecture and Flow

### 3.1 Query Pipeline (End-to-End)

```
User Query (natural language, single input)
  │
  ▼
┌─────────────────────────────────────────┐
│ Intent Router (cheap/fast routing model) │
│  - Extract: author constraints, date    │
│    constraints, source-type constraints, │
│    output-shape intent                   │
│  - Classify: single-author / multi-     │
│    author / open-ended                   │
│  - Decompose: multi-part → sub-queries  │
│  - Route: which data plane(s) needed    │
│    (structured DB / thinker corpus /    │
│    company corpus)                       │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Hybrid Retrieval                         │
│  ├── Dense: pgvector cosine similarity  │
│  │   (broader candidate set, 24-60)     │
│  └── Sparse: tsvector/tsquery BM25-     │
│      style full-text search              │
│  Metadata filters: author, date, domain,│
│  source_type, concept_tags              │
│  Combine via Reciprocal Rank Fusion     │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Cross-Encoder Reranker                   │
│  - Score (query, passage) pairs directly│
│  - Dedicated reranker model, not LLM    │
│  - Deterministic, reliable scores       │
│  - Diversity selection (per-doc cap)    │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Context Expansion                        │
│  - Expand winning chunks with adjacent  │
│    chunks from same document             │
│  - Preserve section context              │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Author Selection                         │
│  - Query-driven, not hardcoded           │
│  - Inputs: query topic, domain,          │
│    expertise_tags, role_type, weight,    │
│    corpus evidence quality               │
│  - Output: ranked author set with        │
│    selection reasons                     │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Author-Lens Reasoning (parallel)         │
│  - Separate inference per selected author│
│  - Config-driven reasoning cards          │
│  - Each lens produces structured output  │
│    with citations                        │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Synthesis Agent                          │
│  - Common ground                         │
│  - Major disagreements                   │
│  - What each lens may be missing         │
│  - Decision-relevant variables           │
│  - Highest-risk assumptions              │
│  - Tentative conclusion + confidence     │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ Critic / Red Team                        │
│  - Unsupported claims check              │
│  - False coherence detection             │
│  - Flattened disagreement detection      │
│  - Weak citation flagging                │
│  - Strongest counterargument             │
└─────────────────────────────────────────┘
  │
  ▼
Structured Answer with Citations
```

### 3.2 Data Plane Routing

The system must route queries to the correct data plane(s), not use a single blended retrieval pass:

| Query Type | Data Plane | Example |
|------------|-----------|---------|
| Fact queries | Plane A — Structured DB | "How many GOOGL shares do I hold?" |
| Research queries | Plane C — Company corpus | "Summarize Novo Nordisk's latest earnings." |
| Concept queries | Plane B — Thinker corpus | "What makes a durable moat?" |
| Judgment queries | Plane A + B + C | "Analyze Meta using Buffett, Marks, Mauboussin lenses." |

### 3.3 Three User-Facing Modes

#### Mode 1: Concept Mode (Issue 131)

- Single-input question about investing/business concepts
- Returns: relevant passages, distinct author perspectives, synthesis, critique, suggested readings
- This is how the system becomes materially better than generic chat

#### Mode 2: Company Thesis Mode (Issue 132)

- User submits a thesis for pressure-testing
- System: pulls author perspectives, surfaces missing questions and blind spots, fetches real-world evidence, identifies thesis strengths and weaknesses
- Returns: structured pressure-test with updated thesis view
- Highest-value mode for investment decision-making

#### Mode 3: Research Memory Mode (Issue 133)

- Save and retrieve research by company, concept, topic, checklist, thesis
- Makes repeated use compound knowledge instead of starting from zero
- Retrieves: prior research, stored notes, extracted evidence, past conclusions, key references

---

## 4. Data Model Concepts and Key Entities

### 4.1 Query-Time Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `rag_queries` | Query audit trail | id, query_text, mode, intent_json, retrieval_config, answer_text, latency_ms, created_at |
| `rag_query_selected_authors` | Author selection log | query_id, author_id, selection_reason, selection_score |
| `rag_query_evidence` | Retrieved evidence log | query_id, chunk_id, author_id, retrieval_rank, retrieval_score, rerank_score |
| `rag_query_lens_outputs` | Per-author reasoning output | query_id, author_id, output_json |
| `rag_query_syntheses` | Synthesis output | query_id, output_json |
| `rag_query_critiques` | Critic output | query_id, output_json |

### 4.2 Research Memory Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `research_notes` | Saved research artifacts | id, title, content, note_type (research/thesis/checklist), created_at |
| `research_note_tags` | Topic/company/concept tagging | note_id, tag_type (company/concept/topic), tag_value |
| `research_note_evidence` | Links notes to source evidence | note_id, chunk_id, source_description |

### 4.3 Hybrid Retrieval Infrastructure

| Component | Implementation |
|-----------|---------------|
| Dense index | pgvector IVFFlat cosine, existing `rag_embeddings` table |
| Sparse index | New `tsvector` column on `rag_chunks` + GIN index |
| Full-text search | Postgres native `to_tsvector` / `to_tsquery` / `ts_rank` |
| Fusion | Reciprocal Rank Fusion (RRF) with configurable k parameter |

---

## 5. API / Workflow Contracts

### 5.1 Query APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ai-sage/query` | Main query endpoint — routes to appropriate mode |
| POST | `/rag/query` | Direct corpus query with retrieval parameters |
| POST | `/rag/analyze/company` | Company analysis with thinker lenses |

### 5.2 Query Request Shape

```json
{
  "question": "string",
  "mode": "concept | company_thesis | research_memory",
  "company": "optional string — ticker or name",
  "thesis": "optional string — user's thesis for pressure-testing",
  "filters": {
    "authors": ["optional author_id constraints"],
    "date_range": { "start": "ISO date", "end": "ISO date" },
    "source_types": ["letter", "memo", "transcript"],
    "concepts": ["moat", "capital_allocation"]
  }
}
```

### 5.3 Query Response Shape

```json
{
  "answer": "string — direct answer",
  "evidence": [
    {
      "chunk_id": "uuid",
      "text": "passage text",
      "author": "author name",
      "work_title": "source title",
      "published_at": "date",
      "retrieval_score": 0.85,
      "rerank_score": 0.92
    }
  ],
  "selected_authors": [
    {
      "author_id": "string",
      "name": "string",
      "selection_reason": "string"
    }
  ],
  "lens_outputs": [
    {
      "author": "string",
      "perspective": "string",
      "key_points": ["string"],
      "citations": ["chunk_id references"]
    }
  ],
  "synthesis": {
    "common_ground": "string",
    "disagreements": "string",
    "missing_information": "string",
    "decision_variables": "string",
    "highest_risk_assumptions": "string",
    "tentative_conclusion": "string",
    "confidence": 0.0-1.0
  },
  "critic": {
    "unsupported_claims": ["string"],
    "false_coherence_flags": ["string"],
    "strongest_counterargument": "string",
    "weakest_claim": "string"
  },
  "suggested_readings": ["source references"],
  "metadata": {
    "query_id": "uuid",
    "mode": "string",
    "latency_ms": 0,
    "retrieval_config": {}
  }
}
```

### 5.4 Research Memory APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/research/notes` | Save a research note |
| GET | `/research/notes` | List/search saved research notes |
| GET | `/research/notes/{id}` | Get a specific research note |
| GET | `/research/notes/by-company/{ticker}` | Get all notes for a company |
| GET | `/research/notes/by-concept/{concept}` | Get all notes for a concept |

---

## 6. Component Design Details

### 6.1 Intent Router (Issues 137, 138)

**Purpose:** Understand the user's query before retrieval to prevent semantic-intent failures.

**Implementation:**
- Cheap, fast routing model (e.g., Qwen 2.5 7B or equivalent) — not the main synthesis model
- Runs before retrieval, adds negligible latency compared to embedding + retrieval
- Configurable independently from the answer-generation model

**Extracts:**
- Explicit author mentions (e.g., "What would Buffett say about …")
- Source/doc-type constraints (e.g., "from his letters")
- Date/time constraints (e.g., "2020 to 2025")
- Output-shape intent (e.g., aphorisms, life advice, investment advice)
- Single-author vs. multi-author vs. open-ended classification
- Query decomposition for multi-part questions

**Routing decision:**
- Which data plane(s) to query
- Which metadata filters to apply
- How many authors to consider

### 6.2 Hybrid Retrieval (Issue 142)

**Why hybrid matters:**
- Dense vector search excels at semantic similarity but fails on proper nouns, exact phrases, rare terms, and high-precision factual queries
- Sparse/keyword retrieval handles exact matches, entity names, specific years, and technical terms
- Research shows combining them with RRF improves recall by 15-30%

**Implementation:**
```
User query
  ├── embed_query() → pgvector cosine distance → dense results
  └── to_tsquery()  → tsvector ts_rank         → sparse results
       │
       ▼
  Reciprocal Rank Fusion (RRF)
       │
       ▼
  Combined ranked results → metadata filtering → candidate set
```

**Database requirements:**
- New `tsvector` column on `rag_chunks` (auto-populated via trigger or on insert)
- GIN index on the tsvector column
- Configurable weighting between dense and sparse scores

### 6.3 Cross-Encoder Reranking (Issue 141)

**Problem with current approach:**
- LLM-prompt-based reranking is slow, expensive, unreliable (JSON parsing fragility), and less accurate than purpose-built rerankers
- Heuristic fallback (keyword overlap + cosine) is barely better than random

**Target architecture:**
- Dedicated cross-encoder reranker service (`api/app/rag/reranker.py`)
- Provider options: Cohere Rerank (recommended), Jina Reranker (alternative), local model fallback
- Scores (query, passage) pairs directly — no JSON parsing fragility
- Faster and cheaper than generative LLM call
- Deterministic, reliable relevance scores

**Diversity selection:**
- Per-document cap (e.g., max 2 chunks per document) to prevent motif collapse
- Author balancing to prevent prolific authors from dominating evidence

### 6.4 Context Expansion (Issue 138)

- After reranking selects the top evidence chunks, expand each winning chunk with adjacent chunks from the same document
- Preserves section context so the synthesis model has enough surrounding information
- Expansion window: configurable (e.g., ±1 chunk from the same document)

### 6.5 Author Selection (Issues 130, 131, PRD-Module-2 §7.3)

**Selection inputs:**
- Query topic and intent (from intent router)
- Requested domain (investing, business, operator, etc.)
- Author expertise_tags and role_type
- Author overall_weight
- Author corpus quality and retrieval strength for this specific query
- Available supporting evidence

**Selection principles:**
- No permanent "core four" authors
- High-weight authors excluded if weakly relevant
- Low-weight authors included when query strongly matches their expertise
- Operator questions prefer operator voices over pure investors
- May return 2 lenses for one query and 5 for another

**Selection output:**
- Ranked author set with selection reasons
- Authors considered but not selected (for debugging/audit)

### 6.6 Author-Lens Reasoning (PRD-Module-2 §7.4)

- Separate inference calls per selected author using config-driven reasoning cards
- Each card includes: domain fit, role type, focus areas, avoid patterns, known biases, output schema
- Cards are loaded from author config, not hardcoded in code
- The system must allow additional cards entirely from config without code-level special casing

### 6.7 Synthesis (PRD-Module-2 §7.5)

The synthesis layer must explicitly output:
- Common ground across lenses
- Major disagreements (not smoothed away)
- What each lens may be missing
- Decision-relevant variables
- Missing information
- Highest-risk assumptions
- Tentative conclusion
- Confidence level (bounded scale)

### 6.8 Critic / Red Team (PRD-Module-2 §7.6)

The critic layer must explicitly check:
- Did synthesis flatten meaningful disagreement?
- Did any lens rely on unsupported claims?
- Are citations actually supportive?
- Which claim is least grounded?
- What is the strongest counterargument?
- What would break this conclusion?

This is a first-class stage, not an optional flourish. It is mandatory for high-value analysis.

---

## 7. Quality Requirements and Failure Behavior

### 7.1 Retrieval Quality

- Hybrid retrieval must improve recall over pure dense search for entity names, exact phrases, and factual queries
- Reranking must produce stable, reproducible relevance scores
- Evidence pack must contain semantically diverse passages (not all from the same motif)
- Author balancing must prevent one prolific author from dominating results

### 7.2 Answer Quality

- Concept mode answers must feel materially better than generic ChatGPT
- Company thesis mode must surface non-obvious pushbacks and missing questions
- Every non-trivial claim must cite supporting passages with enough metadata to verify
- Author distinctions must be preserved — no voice collapse into generic finance wisdom

### 7.3 Latency

- Intent routing: < 500ms
- Retrieval + reranking: < 2s
- Full pipeline (query to answer): < 15s for concept mode, < 30s for company thesis mode
- Research memory retrieval: < 3s

### 7.4 Failure Behavior

| Failure | Expected Behavior |
|---------|-------------------|
| Intent router fails | Fall back to broad retrieval without metadata constraints |
| Dense retrieval returns no results | Return sparse-only results if available; report low confidence |
| Sparse retrieval returns no results | Use dense-only results (current baseline behavior) |
| Reranker API unavailable | Fall back to heuristic ranking (cosine + keyword overlap); log degradation |
| Author lens inference fails for one author | Continue with remaining authors; note missing lens in output |
| Synthesis detects insufficient evidence | Return partial answer with explicit "insufficient evidence" flag |
| Embedding API down during query | Return error with clear message; do not return fabricated results |

---

## 8. Reconciliation Notes

### 8.1 Single Agent vs. Multi-Plane Architecture

- **PRD-Module-2.1** described a "personal judgment operating system" with many integrated layers (knowledge, perspective, synthesis, critic, decision, review/calibration).
- **PRD-Platform-Intelligence-Strategy** explicitly argued against a single blended "super-agent" and for separate data planes with a query router.
- **Resolution:** PRD 3 follows the multi-plane architecture. The intent router determines which plane(s) a query requires. Structured finance questions go to the DB, not through RAG. Thinker and company corpora are separate retrieval targets.

### 8.2 Reranking Approach

- **Issue 138** described the existing LLM-prompt-based reranking approach.
- **Issue 141** explicitly recommended replacing it with a dedicated cross-encoder reranker.
- **Resolution:** Cross-encoder reranking is the target architecture. LLM-prompt reranking is removed. Heuristic ranking serves as emergency fallback only.

### 8.3 Retrieval: Dense-Only vs. Hybrid

- **Issue 128/130** implemented pure dense vector search via pgvector.
- **Issue 142** proposed adding sparse retrieval via Postgres tsvector/tsquery with RRF fusion.
- **Resolution:** Hybrid retrieval (dense + sparse + RRF) is the target. Pure dense is the interim state until sparse infrastructure is built.

### 8.4 Decision Memo Scope

- **PRD-Module-2.1** extensively described Decision Memos, Outcome Reviews, and Calibration Records as core system objects.
- **Issue 131** narrowed v1 to concept mode only, deferring heavy memo workflows.
- **Issue 135** explicitly collected all later-layer work (decision memos, feedback, outcome review, calibration) as deferred.
- **Resolution:** PRD 3 delivers the three core modes (concept, company thesis, research memory). Decision memos, outcome reviews, and calibration belong to deferred scope (§13).

### 8.5 Company Research: Fetch vs. Stored Corpus

- **Issue 132** (Company Thesis Mode) relies on live web evidence fetching for company research.
- **Issue 134** adds persistence of that fetched evidence into a reusable company research corpus.
- **Resolution:** Company thesis mode fetches live evidence AND retrieves from the stored company research corpus (populated by PRD 2). Both sources contribute to the evidence pack.

---

## 9. Acceptance Criteria

- [ ] Intent router extracts author, date, source-type, and output-shape constraints from natural language queries
- [ ] Hybrid retrieval combines dense vector search and sparse keyword search via RRF
- [ ] Cross-encoder reranker scores (query, passage) pairs directly without LLM-prompt fragility
- [ ] Author selection is query-driven and dynamic; no hardcoded author set
- [ ] Concept mode returns differentiated author perspectives, synthesis, critique, and reading suggestions
- [ ] Company thesis mode surfaces missing questions, blind spots, and thesis strengths/weaknesses
- [ ] Research memory mode saves and retrieves notes by company, concept, topic
- [ ] Every non-trivial claim cites supporting passages with author, title, date metadata
- [ ] Synthesis explicitly preserves disagreements and does not produce smooth-but-shallow output
- [ ] Critic stage runs on every high-value analysis (not optional)
- [ ] Fact queries about personal finances are routed to structured DB, not through RAG
- [ ] Query audit trail logs queries, retrieved evidence, and scores

---

## 10. Verification Plan

### 10.1 Deterministic Checks

| Check | Command / Method | Pass Criteria |
|-------|-----------------|---------------|
| Intent routing works | POST `/ai-sage/query` with "What did Buffett say about float?" | Intent extracts author=buffett, concept=float |
| Hybrid retrieval returns results | POST `/rag/query` with entity name query | Both dense and sparse results contribute |
| Reranker produces scores | POST `/ai-sage/query` with concept query | Evidence pack has rerank_score fields |
| Author selection is dynamic | Same query twice with different corpus | Different authors may be selected |
| Concept mode produces full output | POST `/ai-sage/query` mode=concept | Response includes evidence, lenses, synthesis, critic |
| Company thesis mode works | POST `/ai-sage/query` mode=company_thesis with thesis | Response includes pressure-test structure |
| Research notes saved | POST `/research/notes` | Note persisted and retrievable by tag |
| Citations present | Any non-trivial query | Every claim links to chunk_id |

### 10.2 Scenario Checks

| Scenario | Expected Outcome |
|----------|-----------------|
| Single-author query ("What does Buffett think about moats?") | Only Buffett lens returned; other authors not forced |
| Multi-author query ("Compare Buffett and Marks on risk") | Both lenses returned; synthesis highlights disagreements |
| Entity name query ("See's Candies") | Sparse retrieval contributes results that dense may miss |
| Thesis pressure-test | System surfaces non-obvious counterarguments |
| Save and retrieve research | Prior research found by company ticker |

---

## 11. Dependency Map

```
PRD 3 (Retrieval) depends on PRD 2 (Ingestion):
  - Retrieval queries the corpus that PRD 2 builds
  - Chunk metadata quality determines filter effectiveness
  - Embedding quality determines vector search quality
  - tsvector column (for sparse search) populated during ingestion

PRD 4 (Eval) depends on PRD 3 (Retrieval):
  - Evaluation harness measures retrieval quality of PRD 3's pipeline
  - Golden dataset queries test PRD 3's retrieval + reranking
  - A/B comparison runs PRD 3 pipeline with different configurations

PRD 3 depends on Module 1 (Personal Finance):
  - Fact queries about personal finances are routed to structured DB
  - Portfolio context may be combined with thinker/company evidence
```

---

## 12. Issue Traceability

| Issue | Primary PRD | What was absorbed |
|-------|-------------|-------------------|
| 130 — Intelligence Retrieval and Author Wisdom | **PRD 3** | Retrieval layer, author selection, author wisdom profiles, evidence packaging |
| 131 — AI Sage Concept Mode | **PRD 3** | Concept mode end-to-end, single-input UX, synthesis, critique |
| 132 — AI Sage Company Thesis Mode | **PRD 3** | Company thesis pressure-testing, live evidence, thesis view |
| 133 — Research Memory Mode | **PRD 3** | Save/retrieve research, compounding knowledge |
| 137 — Intent Routing and Query Understanding | **PRD 3** | Pre-retrieval intent routing, constraint extraction, query decomposition |
| 138 — Retrieval Quality, Reranking, Context Expansion | **PRD 3** | Broader retrieval, reranking architecture, context expansion, diversity |
| 141 — Cross-Encoder Reranking | **PRD 3** | Dedicated reranker service, Cohere/Jina providers, removal of LLM-prompt reranking |
| 142 — Hybrid Dense + Sparse Retrieval | **PRD 3** | tsvector/tsquery sparse retrieval, RRF fusion, GIN index |

---

## 13. Deferred Items

| Item | Source | Why Deferred |
|------|--------|-------------|
| Decision Memo workflows | PRD-Module-2.1 §§7-8, Issue 135 | Useful only after core modes produce valuable outputs; see Issue 135 |
| Outcome Review records | PRD-Module-2.1 §9 | Requires decision memos to exist first |
| Calibration engine | PRD-Module-2.1 §10 | Requires outcome reviews to exist first |
| Personal improvement analytics | PRD-Module-2.1 §§11-13, Issue 135 | Later-layer work that does not improve current answer quality |
| Feedback capture beyond simple usefulness | Issue 135 | Scaffolding that should wait for system to prove value |
| Portfolio-wide monitoring dashboards | PRD-Platform-Intelligence-Strategy §6 | Cross-plane reasoning (Plane A+B+C) — Phase 4 work |
| Cross-layer insight generation | PRD-Platform-Intelligence-Strategy §2.4 | Highest-value layer, but requires all planes to be sound first |
| Autonomous company corpus expansion | Issue 134 | Infrastructure scaffolding; does not improve output quality now |
| Full company-intelligence system (Plane C) | PRD-Platform-Intelligence-Strategy §4.3 | Separate build track beyond current scope |
