# RAG Evaluation Architecture

Evals are the mechanism that turns "we changed something in retrieval" into a verifiable claim about whether quality improved or regressed. Without evals, every configuration change is speculation.

This document is the current source of truth for how AI Sage retrieval quality is measured, what the metrics mean, and how rollout decisions are made.

For pipeline context, see [AI Sage Product Architecture](./ai-sage-product-architecture.md) and [Retrieval Architecture](./retrieval.md).

---

## Glossary

| Term | Definition |
|---|---|
| **Golden query** | A curated question known to have relevant passages in the corpus |
| **Relevance judgment** | A human decision about whether a specific chunk is relevant to a specific golden query |
| **Labeled relevant chunk** | A chunk that has been assigned a relevance grade ≥ 1 for a given golden query |
| **Relevance grade** | An integer 0–3: 0=irrelevant, 1=partially relevant, 2=relevant, 3=highly relevant |
| **Golden set** | The complete collection of golden queries and their labeled relevant chunks |
| **Top-k results** | The k chunks returned by the retrieval system for a query; `k=10` is the default |
| **Aggregate metric** | A metric averaged across all golden queries (e.g. mean NDCG@10) |
| **Per-query metric** | The same metric computed for one specific golden query |
| **Per-query rollout gate** | A minimum requirement applied to specific queries with sufficient golden coverage |
| **No-regression threshold** | The maximum allowed drop in an aggregate metric before a change is rejected |
| **Candidate-pool recall** | Whether relevant chunks appear anywhere in the broad candidate pool, regardless of final rank |
| **Low-level retrieval eval** | Eval that runs the raw retrieval layer without the full concept pipeline |
| **Live AI Sage path eval** | Eval that runs queries through `execute_concept_query()` — the same path used in production |
| **Reranker diagnosis** | A benchmark that compares heuristic ranking vs specific reranker providers and input modes |
| **Deterministic fixture seeding** | Loading golden labels from a YAML file and resolving them to exact chunk IDs at seed time |

---

## Relevance Grading Scale

Relevance grades are the judgments that label each chunk's importance for a query. They are used to weight metric calculations.

| Grade | Label | Meaning |
|---|---|---|
| `3` | Highly relevant | Directly answers the query; contains the core concept, argument, or example |
| `2` | Relevant | Addresses the query topic but is not the primary or most direct passage |
| `1` | Partially relevant | Tangentially related; provides some context but is not focused on the query |
| `0` | Irrelevant | No useful relationship to the query |

**In the eval code:** chunks with grade ≥ 1 are counted as "relevant" for Recall and Precision. Chunks with grade ≥ 3 are counted as "high relevance" for per-query gates. The NDCG calculation uses the full 0–3 grade via the gain formula `2^grade − 1`.

---

## Metrics

### NDCG@k — Normalized Discounted Cumulative Gain

**Plain-English meaning**: measures whether the most relevant chunks appear near the top of the results. Chunks ranked higher are worth more than chunks ranked lower. A highly relevant chunk at rank 1 is much better than the same chunk at rank 10.

**Formula**:

$$\text{DCG@k} = \sum_{i=1}^{k} \frac{2^{g_i} - 1}{\log_2(i+1)}$$

$$\text{NDCG@k} = \frac{\text{DCG@k}}{\text{IDCG@k}}$$

where $g_i$ is the relevance grade of the chunk at rank $i$ (0 if not in the golden set), and IDCG@k is the DCG of the ideal ranking (golden chunks sorted by grade descending, truncated to k).

**Range**: 0.0 (worst) to 1.0 (perfect).

**Why it matters**: NDCG is the primary metric because it rewards not only finding relevant chunks but finding the most relevant ones at the top.

**What failure mode it detects**: highly relevant chunks being buried below rank 10; weakly relevant chunks crowding out strongly relevant ones at the top.

**Working example** (k=5, grades [3, 2, 0, 1, 3]):

$$\text{DCG@5} = \frac{2^3-1}{\log_2 2} + \frac{2^2-1}{\log_2 3} + \frac{2^0-1}{\log_2 4} + \frac{2^1-1}{\log_2 5} + \frac{2^3-1}{\log_2 6}$$
$$= \frac{7}{1} + \frac{3}{1.585} + 0 + \frac{1}{2.322} + \frac{7}{2.585} = 7 + 1.893 + 0 + 0.431 + 2.708 = 12.03$$

Ideal order would be [3, 3, 2, 1, 0], so IDCG@5 = 7 + 4.416 + 1.893 + 0.431 + 0 = 13.74.

NDCG@5 = 12.03 / 13.74 ≈ 0.876.

**Limitations**: NDCG@k only considers the top k results. It does not penalize a system that retrieved relevant chunks at ranks 11–50.

---

### Recall@k

**Plain-English meaning**: of all the labeled relevant chunks for this query, what fraction appeared in the top k results?

**Formula**:

$$\text{Recall@k} = \frac{|\text{top-k results} \cap \text{relevant chunks}|}{|\text{relevant chunks}|}$$

where "relevant" means grade ≥ 1.

**Range**: 0.0 to 1.0.

**Why it matters**: if relevant chunks never enter the top k, no amount of reranking can fix the answer quality. Recall measures whether the retrieval system found the right material at all.

**What failure mode it detects**: relevant chunks not being retrieved at all (below rank k), or the candidate pool being too narrow to include them.

**Working example**: query has 5 labeled relevant chunks. Top-10 results contain 3 of them. Recall@10 = 3/5 = 0.60.

**Limitations**: Recall@k treats all relevant chunks equally regardless of grade. It does not distinguish between retrieving a grade-3 chunk and a grade-1 chunk.

---

### Recall@50 and Recall@100

Same formula as Recall@k but with k=50 or k=100.

**Why they matter**: these measure whether relevant chunks appear in the broad candidate pool before ranking, independently of final ranking order. If Recall@50 is high but Recall@10 is low, the problem is ranking quality, not candidate recall. If Recall@50 is low, the problem is retrieval recall — relevant chunks are not entering the pool at all.

This distinction determines whether a regression should be diagnosed in the retrieval layer or the reranking layer.

---

### Precision@k

**Plain-English meaning**: of the top k results, what fraction were actually relevant?

**Formula**:

$$\text{Precision@k} = \frac{|\text{top-k results} \cap \text{relevant chunks}|}{k}$$

**Range**: 0.0 to 1.0.

**Why it matters**: indicates how much noise the retrieval system returns alongside the relevant evidence.

**What failure mode it detects**: a retrieval system that retrieves many irrelevant chunks even though it also finds the relevant ones.

**Working example**: top-5 results contain 3 relevant chunks and 2 irrelevant. Precision@5 = 3/5 = 0.60.

**Limitations**: Precision@k does not account for the order of results within the top k. A system that returns all 5 relevant chunks at ranks 1–5 vs ranks 4–8 will have the same Precision@5 if both sets intersect the relevant set by 3 chunks, but rank order matters for user experience.

---

### MRR — Mean Reciprocal Rank

**Plain-English meaning**: how early does the first relevant chunk appear?

**Formula**:

$$\text{MRR} = \frac{1}{\text{rank of first relevant result}}$$

Returns 0.0 if no relevant chunk appears in the result list.

**Why it matters**: for queries where the user needs to find the answer quickly, the rank of the first relevant hit matters more than aggregate recall.

**What failure mode it detects**: relevant chunks consistently appearing at high ranks (5+) rather than at rank 1 or 2.

**Working example**: first relevant chunk appears at rank 4. MRR = 1/4 = 0.25.

**Limitations**: MRR ignores all results after the first relevant hit. It cannot distinguish between a system that returns 3 relevant chunks vs one that returns only 1.

---

### Relevant-Hit Counts

`relevant_hits@k` = count of chunks with grade ≥ 1 in the top-k results (integer, not a fraction).

`high_relevance_hits@k` = count of chunks with grade ≥ 3 in the top-k results.

These are used in per-query gate checks because absolute counts are easier to reason about than fractions when the golden set has varying sizes across queries.

---

## Per-Query Metrics and Aggregate Metrics

For each golden query, the eval runner computes all metrics listed above at k=5 and k=10 (and k=50, k=100 for retrieval-level evals). These are the **per-query metrics**.

After running all golden queries, the runner averages each metric across all queries to produce **aggregate metrics**:

```json
{
  "config_label": "jina_enabled",
  "num_queries": 45,
  "mean_ndcg@5": 0.4892,
  "mean_ndcg@10": 0.5407,
  "mean_recall@5": 0.4219,
  "mean_recall@10": 0.5610,
  "mean_precision@5": 0.3840,
  "mean_precision@10": 0.3210,
  "mean_mrr": 0.7784,
  "per_query": [...]
}
```

---

## No-Regression Threshold

The no-regression bar defines how much aggregate metrics are allowed to drop before a change is rejected:

| Metric | Minimum allowed delta vs baseline |
|---|---|
| `mean_ndcg@10` | ≥ −0.02 |
| `mean_recall@10` | ≥ −0.02 |

These thresholds are defined in `runner.py`:
```python
_NO_REGRESSION_NDCG_DELTA = -0.02
_NO_REGRESSION_RECALL_DELTA = -0.02
```

A configuration passes the no-regression bar if both `Δndcg@10 ≥ −0.02` **and** `Δrecall@10 ≥ −0.02`.

A configuration is a **clear win** if both `Δndcg@10 ≥ +0.02` and `Δrecall@10 ≥ +0.02`.

Passing the no-regression bar is **necessary but not sufficient** to become the new default. Per-query gates must also pass.

---

## Per-Query Rollout Gates

Per-query gates exist because aggregate improvement can coexist with important individual regressions. A configuration that improves the average by +0.03 while destroying a specific query that users ask frequently is not safe to promote.

Gates are evaluated by `evaluate_per_query_gates()`. A query qualifies for gating when it has:
- `golden_relevant_count ≥ 5` (enough relevant chunks to be meaningful)
- `golden_high_relevance_count ≥ 1` (at least one highly relevant chunk)

For qualifying queries, the requirements are:

| Requirement | Value |
|---|---|
| `min_high_relevance_hits@5` | 1 |
| `min_relevant_hits@10` | `min(3, golden_relevant_count)` |
| No regression on `ndcg@10` vs baseline | `current ≥ baseline` |
| No regression on `recall@10` vs baseline | `current ≥ baseline` |

For queries where `retrieved_count ≥ 50` (retrieval-level eval), additional requirements apply:

| Requirement | Value |
|---|---|
| `min_high_relevance_hits@50` | `min(3, high_relevance_count)` |
| `min_relevant_hits@50` | `min(8, relevant_count)` |
| No regression on `recall@50` vs baseline | |

The gate output per query is:
```json
{
  "query": "What are Charlie Munger's main mental models?",
  "requirements": {...},
  "passed": false,
  "failures": ["high_relevance_hits@5 0 < 1", "ndcg@10 regressed 0.41 < 0.58"]
}
```

A change should not be promoted to default if any gated query has `passed: false`.

---

## Candidate-Pool Recall

Candidate-pool recall measures whether relevant chunks appear **anywhere** in the broad retrieval pool before ranking, regardless of whether they made the final top-10.

This is measured by running retrieval with a larger top-k (e.g. k=50 or k=100) and computing Recall@50 and Recall@100. It is exposed in `PerQueryMetrics`:

```
relevant_hits@50, relevant_hits@100
high_relevance_hits@50, high_relevance_hits@100
```

**How to diagnose from these numbers:**

| Pattern | Diagnosis |
|---|---|
| Recall@50 high, Recall@10 low | Chunks are entering the pool but reranking is burying them. Fix: reranking/fusion. |
| Recall@50 low | Chunks are not entering the candidate pool. Fix: retrieval recall (dense/sparse query, hardening thresholds). |
| High-relevance hits@50 low | Highly relevant chunks are missing from the pool entirely. Critical. |

---

## Low-Level Retrieval Eval

The `run` command (`python -m app.rag.eval.cli run`) runs each golden query through the raw retrieval layer only, bypassing `execute_concept_query()` and the full concept pipeline. It uses `run_evaluation()` which calls the retrieval function directly.

**Use this when**: diagnosing whether a problem is in retrieval (candidate quality) vs the concept pipeline (intent parsing, author selection, reranking config).

---

## Live AI Sage Path Eval

The `run-ai-sage` command (`python -m app.rag.eval.cli run-ai-sage`) runs each golden query through `execute_concept_query()` — the exact same function called by the production UI.

**Use this when**: measuring the quality of the full production path, including intent parsing, author selection, topic-focus gate, adaptive reranking, and diversity selection.

This distinction between low-level retrieval eval and live-path eval is important because the production path contains technology choices that do not exist in the raw retrieval benchmark: the routing LLM, author selection logic, Jina reranking, and production audit behavior. Keeping both modes makes it possible to say whether a regression came from retrieval itself or from a later stage in the stack.

The live eval respects all env vars that affect production behavior:
- `RAG_RERANKER_PROVIDER` — whether Jina is active
- `RAG_RERANKER_BLEND_ALPHA` — blend alpha value
- `RAG_RETRIEVAL_HARDENING` — whether hardening is on

---

## Reranker Diagnosis

The `diagnose-reranker` command benchmarks multiple reranker configurations against the golden set:

```bash
docker compose exec -T api python -m app.rag.eval.cli diagnose-reranker \
  --top-k 10 \
  --candidate-pool-size 40 \
  --output /app/data/reports/diagnosis.json
```

It runs:
1. Heuristic ranking (no reranker) as the baseline.
2. Jina reranker with each configured input mode (`raw`, `compact_context`, `expanded_context`).
3. Optionally Cohere or local cross-encoder when `--include-cohere` or `--provider local` is specified.

Results include per-experiment aggregate metrics, a comparison against the heuristic baseline, and a recommendation on whether each combination warrants rollout.

---

## Golden Fixture — Creation and Maintenance

### Location

```
api/app/rag/eval/fixtures/rag_golden_queries.yaml
```

This is the source of truth for the golden set. The database content is derived from this file via the `seed` command.

### YAML Structure

```yaml
golden_queries:
  - query: "What does Buffett say about circle of competence?"
    relevant_chunks:
      - doc_external_id: "1996.html"
        chunk_index: 37
        relevance: 3
      - doc_external_id: "2013ltr.pdf"
        chunk_index: 205
        relevance: 3
      - doc_external_id: "1999htm.html"
        chunk_index: [117, 118]
        relevance: 2
```

| Field | Meaning |
|---|---|
| `query` | The golden query string, exactly as it will be run |
| `doc_external_id` | A substring that matches `RagSource.url` for the document |
| `document_title` | Optional exact title match for `RagDocument.title` (required when a source fans out into multiple logical documents with the same URL) |
| `document_title_contains` | Optional case-insensitive ILIKE match for the document title |
| `source_section_contains` | Optional ILIKE match for `RagDocument.source_section` |
| `chunk_index` | Zero-based index of the chunk within the document (int or list of ints) |
| `relevance` | Integer 0–3 relevance grade |

### Query Selection

Golden queries are selected to cover:
- Distinct concept queries for each major author in the corpus
- Explicit author-attribution queries ("what does X say about Y")
- Broad synthesis queries ("what are the main mental models")
- Queries where retrieval failures would be most damaging to product quality

The current 45-query set (expanded from the original 15) covers Buffett circle of competence, Nick Sleep scale economies shared/Amazon/Kelly/patient capital, Munger mental models/latticework, moat, margin of safety, Mr Market, temperament, intrinsic value, buybacks, and pricing power — across both direct and paraphrased query phrasings.

The golden set lives in YAML rather than being curated only in the database because it needs to be diffable, reviewable, and reproducible with the code that is being tested. A spreadsheet or UI-only labeling workflow could be friendlier for annotation, but it would weaken the connection between a retrieval change and the exact judgments used to accept or reject it.

### Human Curation Process

1. Identify a query that a user would plausibly ask.
2. Run the query through the live system and inspect the retrieved chunks.
3. Search the corpus manually to find the passages that best answer the query.
4. Assign each passage a relevance grade based on how directly it answers the query.
5. Record `doc_external_id`, `chunk_index`, and `relevance` in the YAML file.
6. Rebuild the API image (`make api-rebuild`) and reseed (`seed --replace`).
7. Run a baseline eval to confirm the labels produce meaningful metrics for the query.

### Seed-Time Resolution

The `seed` command resolves YAML entries to actual chunk IDs at seed time:

```python
chunk = (
    db.query(RagChunk)
    .join(RagDocument, RagChunk.document_id == RagDocument.id)
    .join(RagSource, RagDocument.source_id == RagSource.id)
    .filter(
        RagSource.url.contains(doc_external_id),
        RagChunk.chunk_index == idx,
        # optional title filters applied when document_title or document_title_contains is present
    )
    .first()
)
```

If a chunk is not found (because the document has not been ingested yet), the label is **skipped** with a logged warning:

```
WARNING: Chunk not found: doc=1996.html title=None index=37 — skipping
```

This is intentional. The golden set gracefully degrades when documents are unavailable rather than failing the seed.

That behavior is implemented in the CLI seed path against the same Postgres corpus tables used by production retrieval. The alternative would be to fail hard on every missing chunk, but that would make fixture maintenance much more brittle during iterative corpus expansion.

### Skipped Labels and Re-Ingestion Risks

Labels that were skipped at seed time are **not stored** in the DB. They will only be picked up if `seed --replace` is run after the missing document is ingested.

Re-ingesting a document changes chunk indices when the document's structure changes (e.g. different section detection, different parse backend). If this happens, previously correct `chunk_index` values in the YAML may point to the wrong chunks. The YAML file must be re-verified after any re-ingestion that changes document structure.

This is the main maintenance risk of the golden fixture. After any re-ingestion that changes chunk boundaries, run a fresh baseline eval and inspect per-query metrics for unexpected regressions before trusting the results.

---

## Evaluation Workflow

### Step 1 — Seed Labels

```bash
# Rebuild the image with the latest fixture
make api-rebuild

# Seed (or replace) golden labels
docker compose exec api python -m app.rag.eval.cli seed \
  --file app/rag/eval/fixtures/rag_golden_queries.yaml \
  --replace
```

Confirm the output: `Seeded N golden pairs (M skipped)`. If skipped > expected, investigate which documents are missing.

### Step 2 — Run Low-Level Retrieval Eval

```bash
docker compose exec -T api python -m app.rag.eval.cli run \
  --label baseline \
  --top-k 10 \
  --output /app/data/reports/issue174/baseline_retrieval.json
```

This measures raw retrieval quality before the concept pipeline.

The eval path is exposed as a CLI rather than a notebook because rollout decisions need deterministic, repeatable runs that execute inside the API container with the same code and environment variables as production. JSON reports are written to `/app/data/...` so they can be diffed, archived, and compared across experiments.

### Step 3 — Run Live AI Sage Eval

```bash
# Without reranker
docker compose exec -T api python -m app.rag.eval.cli run-ai-sage \
  --label jina_disabled \
  --top-k 10 \
  --output /app/data/reports/issue174/jina_disabled.json

# With Jina reranker
docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api \
  python -m app.rag.eval.cli run-ai-sage \
  --label jina_enabled \
  --top-k 10 \
  --output /app/data/reports/issue174/jina_enabled.json
```

### Step 4 — Compare Configurations

```bash
make rag-eval-drift BASELINE=/app/data/reports/issue174/jina_disabled.json \
  CURRENT=/app/data/reports/issue174/jina_enabled.json
```

Or use the CLI:
```bash
docker compose exec -T api python -m app.rag.eval.cli gate \
  --baseline-report /app/data/reports/issue174/jina_disabled.json \
  --label jina_enabled \
  --top-k 10
```

The comparison output shows:
```json
{
  "passes_no_regression_bar": true,
  "delta_ndcg@10": 0.0526,
  "delta_recall@10": 0.0651,
  "delta_mrr": 0.0295,
  "per_query_gates": [...]
}
```

### Step 5 — Inspect Per-Query Regressions

For any query where `per_query_gates[i].passed = false`:

```bash
docker compose exec api python -m app.rag.eval.cli diagnose-query \
  --query "What are Charlie Munger's main mental models?" \
  --top-k 10 \
  --output /app/data/munger_debug.txt
cat data/munger_debug.txt
```

Inspect the pool memberships of the top results and identify where the regression occurred (candidate pool, gate pruning, fusion, or reranking).

### Step 6 — Diagnose Rerankers and Candidate Pools

```bash
docker compose exec -T api python -m app.rag.eval.cli diagnose-reranker \
  --top-k 10 \
  --candidate-pool-size 40 \
  --output /app/data/reports/reranker_diagnosis.json
```

The diagnosis runs heuristic vs all configured reranker+input-mode combinations. Compare:
- `mean_ndcg@10` for each combination
- `mean_recall@50` to check candidate pool quality vs ranking quality

### Step 7 — Retain or Remove One Isolated Optimization

Make one isolated change at a time. Evaluate it. Check:

1. `passes_no_regression_bar` = true
2. All per-query gates for gated queries = passed
3. No query in the top-10 regressions by `Δndcg@10` shows a drop larger than what the aggregate gain justifies

If all pass: mark the change as **keep**.
If any fail: mark the change as **reject** and revert to the previous state.

### Step 8 — Record Evidence

For every tested configuration, record in the issue journal (the task file for the relevant issue):

- configuration tested (env vars, code change description)
- aggregate metrics for baseline and candidate
- whether no-regression bar passed
- which per-query gates failed (if any)
- keep or reject decision and reasoning

This is the audit trail for every retrieval change. Future engineers can see what was tried and why decisions were made.

### Step 9 — Change Defaults Only After Gates Pass

Update the default configuration (env vars, code constants) only after:

1. No-regression bar passes for aggregate NDCG@10 and Recall@10
2. All per-query gates for gated queries pass
3. The evidence is recorded in the issue journal

---

## Structural Recall Eval

The `structural-recall` command runs a separate class of tests:

```bash
docker compose exec api python -m app.rag.eval.cli structural-recall
```

These are wiring assertions, not quality tests. They verify that `retrieve_by_entity_ids()` and `retrieve_by_concept_ids()` return ≥ 3 candidates for each annotated entity and concept in the corpus. Structural recall failures indicate that entity/concept annotation or indexing is broken.

Structural recall results are reported separately and do **not** affect the no-regression gate thresholds.

---

## Implemented vs Needs Improvement

**Implemented:**
- Query and evidence audit records (`rag_queries`, `rag_query_evidence`)
- Golden fixture YAML with 45 curated queries
- Seed/replace workflow with graceful skip for missing documents
- All metrics: NDCG@5, NDCG@10, Recall@5, Recall@10, Recall@50, Recall@100, Precision@5, Precision@10, MRR, relevant-hit counts, high-relevance-hit counts
- Aggregate and per-query metric reports
- Per-query rollout gates with configurable requirements
- No-regression bar comparison
- Live AI Sage path eval (`run-ai-sage`)
- Low-level retrieval eval (`run`)
- Reranker diagnosis across providers and input modes
- Candidate-pool diagnostics
- Single-query stage trace via `diagnose-query`
- Structural recall eval for entity/concept wiring

**Still needs improvement:**
- UI/debug surface for eval reports (currently JSON files only)
- Fixture maintenance workflow when documents are re-ingested with changed chunk boundaries
- More labeled examples for authors beyond Buffett, Munger, and Sleep
- Future: LLM-assisted judging as a supplement (not replacement) for human labels

---

The evaluation tooling is described where it matters in the workflow above: fixture representation, CLI seeding, metric computation, report generation, and drift comparison are all tied to the stage that uses them.
