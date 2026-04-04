# PRD — Platform Intelligence Strategy

## 0. Product Intent

CapitalOS is evolving from a personal finance dashboard into an intelligence system with four connected goals:

1. Ingest great thinkers and amplify judgment.
2. Answer questions about current personal financial state.
3. Ingest and analyze portfolio-company data and adjacent market intelligence.
4. Apply strong reasoning frameworks to personal and company data to generate better insights.

The key design decision is that these are not one monolithic AI module. They are separate data and reasoning planes that must work together without collapsing into generic, ungrounded output.

---

## 1. Strategic Goals

- Build a trustworthy system that can answer fact questions about current financial state.
- Build a durable research layer for portfolio companies and watchlist companies.
- Build a thinker-amplification layer that sharpens judgment rather than roleplaying authors.
- Preserve traceability, disagreement, and uncertainty instead of producing smooth but shallow synthesis.
- Keep the system local-first, deterministic where possible, and modular enough to evolve incrementally.

---

## 2. Core Product Capabilities

### 2.1 Personal Finance Intelligence

Examples:
- How many GOOGL shares do I hold?
- How long have I held them?
- What did I spend last month?
- What is my cash position by country or platform?

This capability is primarily **structured-data intelligence**, not RAG-first.

Primary source of truth:
- Postgres financial data model
- holdings, transactions, accounts, positions, wallets, snapshots, classifications

Reasoning approach:
- deterministic query layer first
- optional narrative explanation on top

### 2.2 Thinker Amplification

Examples:
- How would different high-quality reasoning frameworks analyze this business?
- What are the strongest counterarguments to my thesis?
- Where is my thinking shallow or overconfident?

This capability is **RAG + reasoning framework**, not roleplay.

Primary source of truth:
- thinker corpus
- authored writings, speeches, memos, letters, transcripts, essays

Reasoning approach:
- query-selected author-lens analysis
- synthesis
- critic

### 2.3 Company Intelligence

Examples:
- What changed at a portfolio company this quarter?
- What is the business model, moat, competition, and current risk surface?
- What do recent transcripts, filings, and product announcements imply?

This capability is **domain research intelligence**.

Primary source of truth:
- company filings
- earnings transcripts
- product/news updates
- competitor information
- selected market/reference metadata

Reasoning approach:
- document retrieval
- company analysis templates
- monitoring/checklist views

### 2.4 Cross-Layer Insight Generation

Examples:
- Which current holdings deserve deeper scrutiny?
- Which portfolio names look strongest under Buffett vs Marks vs Mauboussin lenses?
- Which names combine strong company quality with weak market expectations?

This capability is the highest-value layer and comes only after the first three are sound.

---

## 3. Architectural Principle

The platform must not use a single blended “super-agent” for everything.

That approach fails because:
- structured personal-finance questions get routed through unnecessary RAG
- company research gets mixed with generic author wisdom
- author distinctions collapse into finance-flavored platitudes
- disagreement and tension disappear too early

Instead, CapitalOS should use:
- separate data planes
- a query/router layer
- explicit reasoning stages
- traceable synthesis

---

## 4. Recommended Platform Architecture

## 4.1 Plane A — Structured Personal Finance Data

Purpose:
- answer current-state questions about the user’s own finances

Inputs:
- accounts
- holdings
- positions
- transactions
- spending categories
- snapshots
- market prices already stored in DB

Output examples:
- factual answers
- summaries
- time-series
- allocation and exposure views

Rules:
- DB query first
- no thinker lens required for simple fact retrieval
- no semantic retrieval required for holdings/spending questions

## 4.2 Plane B — Thinker Corpus

Purpose:
- provide reasoning lenses and source-grounded intellectual scaffolding

Inputs:
- configurable author corpus
- letters, essays, speeches, interviews, PDFs, articles

Outputs:
- author-lens analysis
- cited passages
- cross-author comparison
- decision-quality prompts

Rules:
- no digital-twin roleplay
- preserve author distinctions
- surface disagreement explicitly
- do not hardcode a privileged author set; select authors by expertise, relevance, evidence quality, and configured weight

## 4.3 Plane C — Company Intelligence Corpus

Purpose:
- analyze businesses and changing reality around portfolio companies

Inputs:
- earnings transcripts
- filings
- investor presentations
- product updates
- competitor announcements
- selected market/news/reference documents

Outputs:
- business model summaries
- moat/competition analysis
- thesis change detection
- monitoring checklists

Rules:
- company evidence should remain separate from thinker evidence
- citations must identify source type, date, and provenance

## 4.4 Plane D — Orchestration / Query Router

Purpose:
- determine which plane(s) a user query requires

Routing examples:
- “How many shares of GOOGL do I own?” -> Plane A only
- “Summarize Buffett and Marks views on AAPL quality” -> Plane B only
- “What changed at Tencent this quarter?” -> Plane C only
- “Use Buffett, Marks, and Mauboussin lenses on my current top 10 holdings” -> Plane A + Plane B + Plane C

---

## 5. Reasoning Framework

CapitalOS should use a four-stage reasoning framework wherever judgment quality matters.

### Stage 1 — Retrieval

Retrieve relevant evidence from the appropriate plane(s):
- financial DB facts
- thinker passages
- company documents

### Stage 2 — Lens Analysis

Run separate author-specific reasoning adapters when thinker guidance is needed.

Examples:
- Buffett lens
- Munger lens
- Marks lens
- Mauboussin lens
- Thompson lens

Important:
- these are examples, not a fixed canonical set
- the query should determine which authors are invoked
- weights may bias selection, but should not create permanent pedestal authors
- operators and later non-investment domains should fit the same architecture

### Stage 3 — Synthesis

Produce:
- common ground
- key disagreements
- what each lens is missing
- decision-relevant variables
- highest-risk assumptions
- tentative conclusion
- confidence level

### Stage 4 — Critic / Red Team

Check:
- unsupported claims
- false coherence
- flattened disagreement
- weak citations
- strongest counterargument

This stage is mandatory for high-value analysis.

---

## 6. Product Modules

### Module 1 — Personal Finance Control Plane

Already exists in current architecture direction.

Purpose:
- net worth
- holdings
- spending
- trends
- allocations

Primary mode:
- structured data

### Module 2 — Thinker Intelligence RAG

Purpose:
- ingest thinker corpus
- build author lenses
- support synthesis + critic reasoning

Primary mode:
- RAG + lens reasoning

### Module 3 — Company Intelligence

Purpose:
- ingest portfolio-company research data
- produce structured company analysis and monitoring

Primary mode:
- company-document intelligence

### Module 4 — Portfolio Judgment Engine

Purpose:
- apply thinker lenses to personal holdings and company intelligence

Primary mode:
- cross-plane reasoning

---

## 7. Query Model

CapitalOS should support three query classes from day one of the intelligence architecture.

### 7.1 Fact Queries

Examples:
- What is my current DBS cash balance?
- How many Microsoft shares do I hold?
- What were my top 3 spending categories last month?

Answer source:
- structured DB and APIs only

### 7.2 Research Queries

Examples:
- Summarize Novo Nordisk’s latest earnings transcript.
- What are the main competitive threats to Tencent?

Answer source:
- company intelligence corpus

### 7.3 Judgment Queries

Examples:
- Analyze Meta using Buffett, Marks, and Mauboussin lenses.
- What is the strongest case against my Google position?
- Which of my holdings look weakest under second-level thinking?

Answer source:
- thinker corpus + company corpus + portfolio data where needed

---

## 8. Why This Is Better Than A Single Blended Agent

- It preserves useful tension between thinkers instead of averaging them away.
- It keeps factual portfolio answers grounded in the DB.
- It separates company evidence from thinker evidence.
- It makes source attribution and criticism much easier.
- It scales operationally because each plane can evolve independently.

---

## 9. Non-Goals

- A single magical omniscient assistant that answers everything from one retrieval pass.
- Roleplay agents pretending to literally be Buffett, Munger, or Marks.
- Autonomous investment execution.
- Replacing explicit financial data models with embeddings.

---

## 10. Delivery Sequence

### Phase 1

- stabilize personal-finance query layer over current DB
- clean up current API/query semantics for holdings, spending, and snapshots

### Phase 2

- build thinker corpus ingestion and author-lens framework
- citations, synthesis, critic

### Phase 3

- build company intelligence ingestion
- transcripts, filings, competition, business-model analysis

### Phase 4

- combine portfolio data + company intelligence + thinker lenses
- produce portfolio-level judgment workflows

---

## 11. Success Criteria

The strategy is working when:

- fact queries about personal finances are answered directly and correctly from structured data
- thinker-based analysis preserves disagreement and cites sources
- company analysis is document-grounded and operationally useful
- portfolio insight workflows combine these layers without collapsing into vague “quality investing” summaries

---

## 12. Immediate Implication For Current PRDs

- `PRD-Module-1.md` remains the structured personal finance base.
- `PRD-Module-2-Investment-Intelligence-RAG.md` should be narrowed to thinker corpus + reasoning framework.
- A future PRD should be created for company intelligence ingestion and portfolio-company analysis.
