# PRD 4 — Eval: Evaluation, Quality Gates, and Continuous Improvement

## 0. Document Purpose

This PRD defines the evaluation, quality measurement, and continuous improvement infrastructure for CapitalOS intelligence — the system that measures whether ingestion and retrieval are actually working. It consolidates and reconciles requirements from PRD-Module-2, PRD-Module-2.1, PRD-Platform-Intelligence-Strategy, and issues 135 and 143.

**Lifecycle boundary:** PRD 4 operates across the full pipeline defined in PRDs 2 and 3. It measures the quality of what PRD 2 ingests and what PRD 3 retrieves. It does not change ingestion or retrieval behavior — it observes, measures, and flags regressions.

---

## 1. Problem Statement and User Jobs

### Problem

There is currently **no way to measure retrieval quality.** When changes are made to the embedding model, chunking strategy, retrieval algorithm, or reranking logic, there is no systematic way to determine whether the change improved or degraded results. The team relies on manual testing via curl, eyeballing evidence passages, and anecdotal feedback. This is not engineering — it is guessing.

Without measurement:
- Ingestion improvements (better parsing, better chunking) cannot be validated
- Retrieval changes (hybrid search, new reranker) cannot be compared to the baseline
- Regressions go undetected until a user notices degraded answers
- There is no foundation for the later calibration and improvement loops the system aspires to

### User Jobs

| Job | Description |
|-----|-------------|
| **Know if retrieval is good** | Run a single command and get objective metrics on how well the system retrieves relevant passages for known queries. |
| **Detect regressions** | After any pipeline change (chunking, embedding, reranking, retrieval), know immediately if quality dropped. |
| **Compare configurations** | Run the same query set against two configurations and see which produces better retrieval. |
| **Build confidence over time** | Accumulate query-evidence data that shows the system is improving, not just changing. |
| **Audit query behavior** | For any past query, see exactly what was retrieved, what was reranked, what was selected, and what the answer was. |

---

## 2. System Boundaries

### In Scope

- Query audit trail: log every query, retrieved chunks, scores, and answers
- Golden dataset management: curated query-passage pairs for offline evaluation
- Standard IR metrics: NDCG@k, Recall@k, MRR, Precision@k
- A/B comparison: run same query set against two retrieval configurations
- Regression detection: `make rag-eval` that fails if metrics drop below thresholds
- Answer quality signals: basic usefulness feedback on queries
- Ingestion quality metrics: chunk size distribution, parse completeness, embedding coverage
- Pipeline health monitoring: latency tracking, error rates, job success rates

### Out of Scope

- Ingestion pipeline implementation (PRD 2)
- Retrieval pipeline implementation (PRD 3)
- Decision memo workflows and outcome reviews (deferred — see §12)
- Calibration engine (personal confidence calibration over time)
- Personal improvement analytics and bias pattern detection
- Autonomous model fine-tuning based on evaluation results
- User-facing analytics dashboards (eval is developer/operator tooling in v1)

---

## 3. Architecture and Flow

### 3.1 Evaluation System Overview

```
┌──────────────────────────────────────────────────────────┐
│                   Query Audit Trail                       │
│  (Automatic — logs every production query)                │
│                                                           │
│  rag_queries → rag_query_evidence → rag_query_lens_outputs│
│  Records: query text, intent, config, evidence, scores,   │
│           answer, latency                                 │
└──────────────────────────────────────────────────────────┘
        │
        ▼ (feeds)
┌──────────────────────────────────────────────────────────┐
│                   Golden Dataset                          │
│  (Curated — human-labeled query-passage relevance pairs)  │
│                                                           │
│  eval_golden_queries → eval_golden_relevance              │
│  Records: query text, expected mode, relevant chunk_ids,  │
│           relevance grades (0-3)                          │
└──────────────────────────────────────────────────────────┘
        │
        ▼ (evaluated against)
┌──────────────────────────────────────────────────────────┐
│                   Evaluation Engine                        │
│  (On-demand — triggered by `make rag-eval` or CLI)        │
│                                                           │
│  Runs golden queries through retrieval pipeline            │
│  Computes: NDCG@k, Recall@k, MRR, Precision@k            │
│  Compares: config A vs config B                            │
│  Outputs: metrics report, pass/fail against thresholds    │
└──────────────────────────────────────────────────────────┘
        │
        ▼ (reports to)
┌──────────────────────────────────────────────────────────┐
│                   Regression Gate                          │
│  (CI-integrated — fails build if quality drops)           │
│                                                           │
│  Threshold: NDCG@10 ≥ X, Recall@10 ≥ Y, MRR ≥ Z         │
│  Output: pass/fail with metric deltas                     │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow for Evaluation

```
Golden query set (YAML/JSON fixture or database)
  │
  ▼
For each golden query:
  │
  ├── Run query through retrieval pipeline (PRD 3)
  │     → Get ranked list of retrieved chunk_ids with scores
  │
  ├── Compare retrieved chunks against golden relevance labels
  │     → Compute per-query metrics
  │
  └── Aggregate across all queries
        → Compute corpus-level metrics
        → Compare against thresholds
        → Compare against baseline (if A/B mode)
        → Output report
```

---

## 4. Data Model Concepts and Key Entities

### 4.1 Query Audit Trail Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `rag_queries` | Log every query | id, query_text, mode, intent_json, retrieval_config (snapshot), answer_text, latency_ms, created_at |
| `rag_query_evidence` | Link queries to retrieved chunks | id, query_id, chunk_id, author_id, retrieval_rank, dense_score, sparse_score, rrf_score, rerank_score, selected (boolean) |

These tables serve dual purposes:
1. Production observability (what happened for this query?)
2. Evaluation data source (mine production queries to discover new golden dataset candidates)

### 4.2 Golden Dataset Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `eval_golden_queries` | Curated evaluation queries | id, query_text, expected_mode, description, category (concept/company/entity/date), created_at |
| `eval_golden_relevance` | Human-labeled relevance judgments | id, golden_query_id, chunk_id, relevance_grade (0=irrelevant, 1=marginal, 2=relevant, 3=highly relevant), notes |

### 4.3 Evaluation Run Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `eval_runs` | Track evaluation executions | id, config_snapshot (JSON), golden_set_id, metrics_json, passed (boolean), created_at |
| `eval_run_details` | Per-query results within a run | id, eval_run_id, golden_query_id, retrieved_chunk_ids (JSON), ndcg, recall, mrr, precision |

### 4.4 Golden Dataset File Format

Golden datasets can also be managed as YAML fixtures for version control:

```yaml
# data/eval/golden_queries.yaml
queries:
  - id: gq-001
    query: "What does Warren Buffett say about float?"
    category: concept
    expected_mode: concept
    relevant_passages:
      - chunk_id: "uuid-of-known-relevant-chunk"
        relevance: 3  # highly relevant
        notes: "2005 letter, insurance section"
      - chunk_id: "uuid-of-another-relevant-chunk"
        relevance: 2  # relevant
        notes: "1998 letter, float discussion"

  - id: gq-002
    query: "See's Candies pricing power"
    category: entity
    expected_mode: concept
    relevant_passages:
      - chunk_id: "uuid"
        relevance: 3
```

---

## 5. API / Workflow Contracts

### 5.1 Evaluation CLI Commands

| Command | Description |
|---------|-------------|
| `make rag-eval` | Run full evaluation suite against golden dataset; fail if below thresholds |
| `make rag-eval-report` | Run evaluation and produce detailed report (no fail on threshold) |
| `make rag-eval-compare CONFIG_A=... CONFIG_B=...` | A/B comparison of two retrieval configurations |

### 5.2 Evaluation APIs (Internal / Admin)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/eval/run` | Trigger an evaluation run |
| GET | `/eval/runs` | List past evaluation runs with summary metrics |
| GET | `/eval/runs/{id}` | Get detailed results for an evaluation run |
| GET | `/eval/golden-queries` | List golden dataset queries |
| POST | `/eval/golden-queries` | Add a new golden query with relevance labels |
| PUT | `/eval/golden-queries/{id}` | Update a golden query |
| GET | `/eval/metrics/latest` | Get the most recent evaluation metrics |

### 5.3 Query Audit APIs (Internal / Admin)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rag/queries` | List recent queries with metadata |
| GET | `/rag/queries/{id}` | Get query detail including all retrieved evidence and scores |
| GET | `/rag/queries/{id}/evidence` | Get evidence details for a specific query |
| POST | `/rag/queries/{id}/feedback` | Submit basic usefulness feedback on a query |

### 5.4 Metrics Output Shape

```json
{
  "eval_run_id": "uuid",
  "config": { "retrieval_mode": "hybrid", "reranker": "cohere", "top_k": 10 },
  "corpus_metrics": {
    "ndcg_at_10": 0.72,
    "recall_at_10": 0.85,
    "mrr": 0.68,
    "precision_at_10": 0.45,
    "num_queries": 50,
    "num_queries_with_results": 48
  },
  "category_breakdown": {
    "concept": { "ndcg_at_10": 0.75, "recall_at_10": 0.88 },
    "entity": { "ndcg_at_10": 0.65, "recall_at_10": 0.78 },
    "date_filtered": { "ndcg_at_10": 0.70, "recall_at_10": 0.82 }
  },
  "thresholds": {
    "ndcg_at_10": { "minimum": 0.60, "actual": 0.72, "passed": true },
    "recall_at_10": { "minimum": 0.70, "actual": 0.85, "passed": true },
    "mrr": { "minimum": 0.50, "actual": 0.68, "passed": true }
  },
  "passed": true,
  "created_at": "ISO timestamp"
}
```

---

## 6. IR Metrics Definitions

### 6.1 Standard Metrics

| Metric | Definition | Why It Matters |
|--------|-----------|----------------|
| **NDCG@k** (Normalized Discounted Cumulative Gain) | Measures ranking quality: relevant passages ranked higher score better. Accounts for graded relevance (highly relevant > relevant > marginal). | The primary metric. Captures both whether relevant passages are retrieved AND whether they are ranked well. |
| **Recall@k** | Fraction of all known-relevant passages that appear in the top-k results. | Measures breadth: are we missing important passages? |
| **MRR** (Mean Reciprocal Rank) | Average of 1/rank of the first relevant result. | Measures whether the user gets something useful quickly. |
| **Precision@k** | Fraction of top-k results that are relevant. | Measures noise: how much irrelevant content is in the evidence pack? |

### 6.2 Relevance Grading Scale

| Grade | Label | Definition |
|-------|-------|-----------|
| 0 | Irrelevant | Passage has no meaningful connection to the query |
| 1 | Marginal | Passage is tangentially related but not directly useful |
| 2 | Relevant | Passage directly addresses the query with useful information |
| 3 | Highly Relevant | Passage is among the best possible evidence for this query |

### 6.3 Default Thresholds

These are starting thresholds and should be adjusted as the corpus and golden dataset mature:

| Metric | Minimum Threshold | Target |
|--------|------------------|--------|
| NDCG@10 | 0.50 | 0.70+ |
| Recall@10 | 0.60 | 0.80+ |
| MRR | 0.40 | 0.60+ |

---

## 7. Ingestion Quality Metrics

PRD 4 also provides quality visibility into the ingestion pipeline (PRD 2):

### 7.1 Corpus Health Metrics

| Metric | Description | Source |
|--------|-------------|--------|
| Total documents ingested | Count of successfully ingested documents | `rag_documents` |
| Total chunks | Count of chunks in corpus | `rag_chunks` |
| Chunk size distribution | Histogram of token counts per chunk | `rag_chunks.token_count` |
| Embedding coverage | Percentage of chunks that have embeddings | `rag_chunks` JOIN `rag_embeddings` |
| Author distribution | Chunk counts per author | `rag_chunks` metadata → author |
| Ingestion success rate | Completed / total ingestion jobs | `rag_ingestion_jobs` |
| Ingestion error categories | Breakdown of failure types | `rag_ingestion_jobs.error` |
| Parse quality distribution | Cleanliness/confidence scores across corpus | `rag_chunks` metadata → cleanliness |

### 7.2 Corpus Health API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/eval/corpus-health` | Summary of corpus quality metrics |
| GET | `/eval/corpus-health/chunks` | Chunk size distribution and statistics |
| GET | `/eval/corpus-health/authors` | Per-author ingestion statistics |

---

## 8. Quality Requirements and Failure Behavior

### 8.1 Evaluation System Quality

- Evaluation runs must be reproducible: same golden dataset + same config = same metrics
- Metrics computation must be mathematically correct per standard IR definitions
- Golden dataset must support graded relevance (not just binary relevant/irrelevant)
- A/B comparison must run both configurations against the exact same query set
- Evaluation must not affect production query behavior (read-only against the pipeline)

### 8.2 Query Audit Quality

- Every production query must be logged (no sampling or dropping in v1)
- Audit data must include the full evidence chain: query → intent → retrieved chunks → scores → selected chunks → answer
- Audit data must be queryable by time range, mode, and performance characteristics
- Query logging must not meaningfully increase query latency (async write or background task)

### 8.3 Failure Behavior

| Failure | Expected Behavior |
|---------|-------------------|
| Golden query references a chunk_id that no longer exists | Skip that relevance judgment; warn in report; do not fail the run |
| Evaluation run times out | Partial results saved; run marked as incomplete |
| `make rag-eval` fails threshold | Exit code 1; CI/CD blocks the change |
| Query audit write fails | Log error; do not fail the production query |
| Corpus health check finds zero embeddings | Report critical warning; do not block queries |

---

## 9. Reconciliation Notes

### 9.1 Evaluation Scope: PRD-Module-2.1 vs. Issue 143

- **PRD-Module-2.1** described a broad "Calibration Engine" that tracked confidence vs. correctness, bias patterns, domain-specific accuracy, lens effectiveness, and personal adaptation over time.
- **Issue 143** scoped evaluation specifically to retrieval quality: IR metrics, golden datasets, and regression detection.
- **Resolution:** PRD 4 covers Issue 143's retrieval evaluation scope as the near-term deliverable. The broader calibration engine (confidence tracking, bias detection, personal adaptation) is deferred to §12 because it requires decision memos and outcome reviews that don't yet exist.

### 9.2 Query Audit Trail: Specified but Not Implemented

- **PRD-Module-2** §10 specified `rag_queries`, `rag_query_evidence`, `rag_query_selected_authors`, `rag_query_lens_outputs`, `rag_query_syntheses`, and `rag_query_critiques` tables.
- **Issue 143** noted that none of these tables exist in the codebase.
- **Resolution:** PRD 4 includes the query audit trail as a core deliverable. The table schema from PRD-Module-2 is adopted with modifications to support evaluation (adding score columns and config snapshots).

### 9.3 Feedback vs. Evaluation

- **PRD-Module-2.1** described rich user feedback (useful/not useful, too generic, missed key risk, overconfident, etc.) as a core workflow.
- **Issue 135** explicitly deferred detailed feedback capture.
- **Resolution:** PRD 4 includes basic usefulness feedback (thumbs up/down + optional free text) as a lightweight signal. Rich structured feedback is deferred with the calibration engine.

---

## 10. Acceptance Criteria

- [ ] Query audit trail logs every query with full evidence chain (query, intent, config, chunks, scores, answer, latency)
- [ ] Golden dataset can be loaded from YAML fixtures and/or managed via API
- [ ] NDCG@k, Recall@k, MRR, and Precision@k are computed correctly per standard IR definitions
- [ ] `make rag-eval` runs the full golden dataset and exits with code 1 if any metric is below threshold
- [ ] A/B comparison runs two configurations against the same query set and reports metric deltas
- [ ] Evaluation runs are stored with config snapshot and are reproducible
- [ ] Corpus health metrics are available via API
- [ ] Query audit does not meaningfully increase production query latency
- [ ] Basic usefulness feedback can be submitted for any query
- [ ] Existing PRD files are not deleted (user reviews before cleanup)

---

## 11. Verification Plan

### 11.1 Deterministic Checks

| Check | Command / Method | Pass Criteria |
|-------|-----------------|---------------|
| Query audit logging | POST `/ai-sage/query`, then GET `/rag/queries` | Query appears in audit trail with evidence |
| Golden dataset loads | Load YAML fixture, GET `/eval/golden-queries` | All queries present with relevance labels |
| Metrics computation | POST `/eval/run` with golden dataset | NDCG, Recall, MRR values returned and mathematically correct |
| Regression gate | `make rag-eval` with known-passing corpus | Exit code 0 |
| Regression gate fails | `make rag-eval` with artificially degraded config | Exit code 1 |
| A/B comparison | POST `/eval/run` with two configs | Both configs evaluated; deltas shown |
| Corpus health | GET `/eval/corpus-health` | Returns chunk counts, embedding coverage, author distribution |

### 11.2 Scenario Checks

| Scenario | Expected Outcome |
|----------|-----------------|
| Change chunking strategy and re-evaluate | Metrics change; direction indicates improvement or regression |
| Add new author to corpus and re-evaluate | Per-author metrics available; overall metrics adjust |
| Golden query references deleted chunk | Warning logged; query skipped; run continues |
| 100 production queries logged | All 100 appear in audit trail with full evidence chains |
| Submit feedback on a query | Feedback stored and retrievable |

---

## 12. Dependency Map

```
PRD 4 (Eval) depends on PRD 2 (Ingestion):
  - Evaluation needs an ingested corpus to evaluate against
  - Corpus health metrics read from ingestion tables
  - Golden dataset references chunks produced by ingestion

PRD 4 (Eval) depends on PRD 3 (Retrieval):
  - Evaluation runs queries through the retrieval pipeline
  - Query audit trail logs retrieval behavior
  - IR metrics measure retrieval quality
  - A/B comparison tests different retrieval configurations

PRD 4 (Eval) has no downstream PRD dependencies:
  - It is an observability and quality layer
  - Future calibration engine (deferred) would build on PRD 4's data
```

---

## 13. Issue Traceability

| Issue | Primary PRD | What was absorbed |
|-------|-------------|-------------------|
| 143 — Retrieval Evaluation Harness | **PRD 4** | Query audit trail, golden dataset, IR metrics, A/B comparison, regression detection, `make rag-eval` |
| 135 — Feedback, Outcome Review, and Improvement Loop | **PRD 4** (partially) | Basic feedback capture absorbed; decision memos, outcome reviews, calibration deferred |

Issues that are fully deferred (not absorbed into any near-term PRD):
| Issue | Reason |
|-------|--------|
| 136 — Auth Session Reliability Breakfix | Orthogonal to intelligence pipeline; remains a standalone infrastructure issue |

---

## 14. Deferred Items

| Item | Source | Why Deferred |
|------|--------|-------------|
| Calibration engine (confidence vs. correctness tracking) | PRD-Module-2.1 §10, Issue 135 | Requires decision memos and outcome reviews; those don't exist yet |
| Outcome review records | PRD-Module-2.1 §9, Issue 135 | Requires decision memos to exist first |
| Personal improvement analytics | PRD-Module-2.1 §§11-13, Issue 135 | Meta-memory patterns require a large history of evaluated decisions |
| Bias pattern detection | PRD-Module-2.1 §11, Issue 135 | Requires calibration data from many reviewed decisions |
| Lens effectiveness tracking | PRD-Module-2.1 §10 | Requires outcome data to correlate lens selection with result quality |
| Automated prompt/retrieval tuning from feedback | PRD-Module-2.1 Workflow 2 | Premature; need baseline metrics first |
| Rich structured feedback (missed key risk, overconfident, etc.) | PRD-Module-2.1 Workflow 2, Issue 135 | Basic usefulness feedback is sufficient for v1 |
| User-facing evaluation dashboards | — | v1 eval is developer/operator tooling; user dashboards come later |
| LLM-as-judge answer quality scoring | Issue 143 (mentioned as future) | Adds complexity and cost; golden dataset + IR metrics are sufficient for v1 |

---

## 15. Future Evolution Path

This section documents how PRD 4's evaluation foundation enables the deferred calibration and improvement features:

```
v1 (PRD 4 scope):
  Query audit trail → Golden dataset → IR metrics → Regression gates

v2 (first deferred layer):
  + Answer quality feedback (structured)
  + Feedback-informed golden dataset expansion
  + Per-author retrieval quality tracking

v3 (calibration layer — requires decision memos from deferred PRD 3 scope):
  + Decision memo → Outcome review linkage
  + Confidence vs. correctness tracking
  + Domain-specific accuracy analysis

v4 (personal adaptation — requires calibration data):
  + Bias pattern detection
  + Lens effectiveness correlation
  + Personal epistemics profile
  + Adaptive retrieval and reasoning tuning
```

Each layer requires the previous to be producing genuine value. This is the "ruthless scope control" principle applied to evaluation: measure what exists before trying to measure what doesn't.
