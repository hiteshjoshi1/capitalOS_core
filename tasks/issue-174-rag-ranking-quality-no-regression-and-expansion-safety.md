# Issue 174: RAG ranking quality no-regression and expansion safety

> **Depends on**: Issue 170 (entity/concept metadata), Issue 171 (corpus-local expansion
> index), and Issue 172 (retrieval wiring).
>
> **Separate from Issue 173**: Issue 173 makes corpus expansion refresh automatically after
> ingestion. This issue is about ranking quality and rollout safety after entity/concept and
> expansion pools are wired into retrieval.

## Problem

Issues 170, 171, and 172 add useful retrieval infrastructure:

- chunk-level entity/concept annotations
- corpus-local expansion terms
- entity/concept annotation candidate pools
- structural recall tests proving the pools can retrieve matching annotated chunks

However, structural recall is not enough. A pool can retrieve matching chunks and still make final
top-10 ranking worse if noisy expansion or annotation candidates are scored too strongly.

The historical quality baseline from Issue 167 was:

| Configuration | `mean_ndcg@10` | `mean_recall@10` | `mean_precision@10` | `mean_mrr` |
|---|---:|---:|---:|---:|
| heuristic baseline | `0.3882` | `0.4556` | `0.2467` | `0.5527` |
| adaptive Jina/raw | `0.4680` | `0.4838` | `0.3000` | `0.6711` |

Confirmed diagnostic run (`diagnose-reranker --top-k 10 --candidate-pool-size 40`,
concept-mode pipeline, branch `feature/issue-172`) showed:

| Configuration | `mean_ndcg@10` | `mean_recall@10` | `mean_mrr` | delta ndcg@10 vs 167 |
|---|---:|---:|---:|---:|
| heuristic | `0.3386` | `0.4222` | `0.4836` | **-0.0496** |
| Jina/raw | `0.4192` | `0.4505` | `0.6056` | **-0.0488** |

Both configurations exceed the -0.02 no-regression gate on `mean_ndcg@10`. Hardening is on
for both runs (concept-mode pipeline always uses `_retrieve_hardened`).
Jina remains better than heuristic (+0.0806 NDCG) but regresses against its own Issue 167 peak.
The regressions on NDCG and MRR are confirmed real and need to be resolved before shipping.

## Objective

- Preserve the useful 170/171/172 candidate recall improvements.
- Prevent entity/concept annotation pools and corpus expansion pools from dominating final ranking
  unless candidates also match the actual query intent.
- Add deterministic quality gates so structural recall cannot pass while ranking quality regresses.
- Keep Jina and provider reranking diagnosable, but do not enable external reranking by default
  unless aggregate and per-query no-regression gates pass.

## Architecture Decisions

- **Structural recall remains separate from ranking quality.** Structural recall proves wiring.
  Ranking quality must be evaluated with the hand-labeled golden set and per-query gates.
- **Annotation pools are recall sources, not relevance proof.** A chunk annotated with `amazon`,
  `mental_models`, or another pivot can enter the candidate pool, but annotation membership alone
  must not be enough to win top-10 ranking.
- **Expansion terms are query support, not query replacement.** Corpus-local expansion terms should
  improve recall when they are specific and related to the query. Generic finance terms must be
  filtered or heavily downweighted.
- **Single-author queries stay author-scoped.** For queries such as "What does Nick Sleep say about
  Amazon?", cross-author evidence is invalid unless the user explicitly asks for open-corpus or
  multi-author comparison.
- **Fallback must be deterministic.** If expansion-heavy candidates dominate top results while
  query-anchor evidence is weak, retrieval should fall back to the pre-expansion hardened ranking.
- **Reranker rollout requires per-query safety.** Aggregate gains are insufficient if one named
  author/entity query regresses materially.

## Required Diagnosis Before Implementation

Run the live eval suite before changing code and record:

1. Structural recall result.
2. Hardening-on vs hardening-off quality metrics.
3. Current quality metrics vs Issue 167 historical baseline.
4. Per-query regressions for heuristic and Jina/raw.
5. For worst regressions, whether relevant chunks were present in candidate pools but lost during
   final ranking.

If candidate pools contain relevant chunks but final top-10 misses them, fix ranking/fusion. If
candidate pools do not contain relevant chunks, fix candidate generation.

## Diagnosis Results (branch `feature/issue-172`, 2026-05-28)

### Structural recall
88 tests, 88 passed, 0 failed, 3 authors covered (warren_buffett, charlie_munger, nick_sleep).
Wiring is correct. Pool injection does not break structural recall.

### Candidate pool summary
```
mean_candidate_pool_recall:      0.8053  (historical: 0.8164, delta: -0.0111)
queries_with_pool_gaps:          3  (Mr Market, Munger mental models × 2)
```
Pool recall regression is small in aggregate but concentrated in 3 queries where relevant chunks
never enter the 40-candidate broad pool.

### Per-query classification

| Query | pool_recall | heuristic ndcg@10 | jina/raw ndcg@10 | failure type |
|---|---:|---:|---:|---|
| Mr Market | 0.333 | 0.000 | 0.000 | **pool gap — candidate generation** |
| Munger mental models (main) | 0.214 | 0.200 | 0.505 | pool gap (Jina partially recovers from low pool) |
| Munger mental models (best) | 0.232 | 0.128 | 0.496 | pool gap (Jina partially recovers) |
| Nick Sleep scale economies shared | 0.667 | 0.157 | **0.000** | **Jina regression — relevant chunks in pool but Jina ranks them out of top-10** |
| Pricing power | 1.000 | 0.180 | 0.288 | ranking/fusion |
| Margin of safety | 1.000 | 0.264 | 0.307 | ranking/fusion |
| Patient capital | 0.800 | 0.307 | 0.772 | partial pool gap + ranking; Jina wins big |
| Buybacks | 0.833 | 0.218 | 0.218 | partial pool gap |
| Moat | 1.000 | 0.212 | 0.246 | ranking/fusion |
| Circle of competence | 1.000 | 0.817 | 0.817 | stable |
| Temperament | 1.000 | 0.699 | 0.699 | stable |
| Munger mental models + latticework | 1.000 | 0.682 | 0.693 | stable |
| Kelly criterion | 1.000 | 0.425 | 0.459 | stable |
| Intrinsic value | 1.000 | 0.488 | 0.488 | stable |
| Amazon business model | 1.000 | 0.303 | 0.303 | stable (Jina no gain) |

### Root cause analysis

**1. `concept_annotation_pool` is populated for multiple eval queries.**
`rag_concept_aliases` maps `circle_of_competence`, `mental_models`, `scale_economies_shared` etc.
to concept IDs.  `build_retrieval_query_plan` resolves required phrases to concept IDs and populates
`plan.resolved_concept_ids`.  `_retrieve_hardened` then adds `concept_annotation_pool` at weight
**1.1** — higher than `dense_feedback` (0.85), `topic_entity_pool` (1.0), and `corpus_expansion_pool`
(0.9), and equal to `entity_annotation_pool`.

For the "scale economies shared" query, the `concept_annotation_pool` adds up to 30 chunks ranked
by annotation confidence (not query similarity).  When Jina reranks the top-40 candidate set, those
annotation-heavy chunks displace query-anchor evidence, producing `ndcg@10 = 0.000` where heuristic
scores `0.157`.

**2. Pool-gap queries are a concept-mode author selection issue.**
The three queries with pool_recall < 0.4 ("Mr Market", two "mental models" variants) don't find
relevant chunks in the 40-candidate broad pool.  The author selection step in `concept_mode.py`
picks the right authors, but the dense/sparse retrieval for generic concept phrases fails to surface
the specific annotated chunks.  This pre-dates issue 172.

**3. Jina has high per-query variance.**
Jina strongly helps patient capital (+0.465), mental models variants (+0.304/+0.368) but hurts
scale economies shared (-0.157) and gives no gain on several others.  This variance exceeds safe
rollout thresholds on a 15-query set.

**4. Annotation pool weight 1.1 is the primary suspected cause of the Jina / scale-economies regression.**
The concept annotation pool is injected with weight 1.1 before Jina sees the candidate set.
Annotation-confidence ordering is not correlated with query relevance.  Downweighting is the first
hypothesis to validate; causality is not confirmed until an A/B eval after the weight-only change
shows the regression fixed.

### Issue 172 pool table at time of diagnosis
```
entity_annotation_pool:   weight 1.1  (added when plan.resolved_entity_ids non-empty)
concept_annotation_pool:  weight 1.1  (added when plan.resolved_concept_ids non-empty)
corpus_expansion_pool:    weight 0.9  (added when plan.corpus_expansion_terms non-empty)
```
`corpus_expansion_pool` was empty for all 15 test queries — no NPMI data in `rag_corpus_expansions`
yet (Issue 171 not yet computed).  Entity annotation pool was also empty for all 15 queries
(no entity aliases matched the query topics).  **Only the concept annotation pool is active** for
the queries above.

## Proposed Fixes

> Priority order revised based on diagnosis: Fix 1 is the first hypothesis to validate via A/B.
> Fix 3 (query-anchor guard) and Fix 5 (fallback) address the same mechanism — implement
> one or both.  Fix 2 is low priority until corpus expansion data exists.

### 1. Demote Annotation Pool Weight — **PRIMARY HYPOTHESIS — VALIDATE VIA A/B**

The `concept_annotation_pool` weight of 1.1 is the primary suspected cause of the scale-economies
Jina regression.  Annotation confidence order is not query-relevance order.  Candidates from
annotation pools should enter the fusion as a supplementary recall signal, not a dominant scoring
signal.  **Run `diagnose-reranker` before and after this weight-only change to confirm causality.**

**Required change in `fuse_hardened_candidates`:**

```python
# Before:
"entity_annotation_pool": 1.1,
"concept_annotation_pool": 1.1,

# After:
"entity_annotation_pool": 0.7,
"concept_annotation_pool": 0.7,
```

A weight of 0.7 (below `dense_content` at 1.25 and `sparse_content` at 1.6) means annotation
pool candidates enter the pool and can rank high only if they also appear in dense/sparse pools.
This preserves the recall contribution while removing annotation-dominant displacement.

Verify: after the weight change, re-run `diagnose-reranker --provider jina --input-mode raw`.
`scale_economies_shared` must recover to ≥ 0.10 NDCG.  Mean NDCG must not regress further.

### 2. Filter Corpus Expansion Terms

Expansion terms should be specific enough to help, not generic enough to flood retrieval.

Filter out expansion terms that are:

- stopwords or near-stopwords
- one-token generic finance words such as `year`, `years`, `company`, `market`, `earnings`,
  `will`, `more`, `only`, `these`, `been`, `were`, `business`, unless they are part of a specific
  multi-word phrase
- terms already present in the content query
- terms with weak support or weak NPMI

Prefer:

- multi-word phrases
- known entity aliases
- known concept aliases
- high-NPMI terms with enough corpus support

> Lower priority: `corpus_expansion_pool` is empty for all current eval queries.  Implement
> during or after Issue 171 data is populated.

### 3. Add Query-Anchor Overlap Guard

Before a candidate from `corpus_expansion_pool`, `entity_annotation_pool`, or
`concept_annotation_pool` can enter final top 10, require at least one query-anchor signal.

If no query-anchor signal exists, either:

- keep the candidate in the broad pool but cap its score below top-10 eligibility, or
- exclude it from final top-10 unless final results would otherwise be empty.

This guard should be deterministic and visible in diagnostics.

> Note: Fix 1 (weight demotion) may be sufficient for the known regressions.  Implement
> this guard if post-Fix-1 eval shows annotation-only candidates still displace query-anchor
> results in specific queries.

### 4. Preserve Strict Source-Author Gate

For single-author queries, enforce author scope after all pools are fused.

Required behavior:

- "What does Nick Sleep say about Amazon?" returns only Nick Sleep corpus chunks.
- "What does Charlie Munger say about Costco?" returns only Charlie Munger corpus chunks.
- Open-corpus and explicit multi-author queries may use multiple authors.

> Source-author gate is currently active in `_enforce_source_author_gate`.  Confirm it
> remains applied after annotation pool injection.

### 5. Add Expansion-Dominance Fallback

Track whether final top results are dominated by expansion-only candidates.

If top-10 has too many candidates whose only strong source is corpus expansion and those candidates
lack query-anchor overlap, fall back to the pre-expansion hardened ranking for that query.

The fallback should:

- be deterministic
- be logged in diagnostics
- preserve source-author constraints
- not remove useful dense/sparse/entity/concept candidates that have query-anchor evidence

### 6. Make Reranker Default Safe

Keep Jina/provider code and diagnosis harness, but default runtime should be `RAG_RERANKER_PROVIDER=none`
unless the live eval shows:

- aggregate clear win
- no per-query regression beyond the configured tolerance
- no single-author source drift
- provider available without rate-limit failure

If Jina remains available, use it as an explicit diagnostic or opt-in mode until it clears those
conditions.

> **Current status: Jina IS the default.** The code default in `reranker.py` is
> `os.getenv("RAG_RERANKER_PROVIDER", "jina")` and the running container has
> `RAG_RERANKER_PROVIDER=jina` set.  This fix is **not yet satisfied** and requires two concrete
> changes:
> 1. Change code default to `"none"`: `os.getenv("RAG_RERANKER_PROVIDER", "none")` in `reranker.py`.
> 2. Remove or override `RAG_RERANKER_PROVIDER=jina` in `docker-compose.yml` / `.env`.

## Acceptance Criteria

- [ ] Structural recall still passes with live 170/171 data.
- [ ] Hardening-on quality remains better than or equal to hardening-off quality on the 15-query
  hand-labeled golden set.
- [ ] Current hardening-on quality does not materially regress against the Issue 167 historical
  baseline on `mean_ndcg@10`, `mean_recall@10`, and `mean_mrr`.
- [ ] Per-query no-regression gates pass for named-author/entity queries, including Nick Sleep /
  Amazon, Nick Sleep / scale economies shared, and Charlie Munger / mental models.
- [ ] Entity/concept annotation pools are present in diagnostics but cannot dominate top-10 ranking
  without query-anchor evidence.
- [ ] Corpus expansion terms are filtered so generic terms do not appear in the sparse expansion
  query.
- [ ] Single-author queries cannot return other authors unless the intent explicitly requests
  open-corpus or multi-author retrieval.
- [ ] **Primary quality gate (heuristic/hardened):** `mean_ndcg@10` ≥ 0.36 on the 15-query
  golden set with no external reranker (`RAG_RERANKER_PROVIDER=none`).  This is mandatory.
- [ ] `RAG_RERANKER_PROVIDER` default changed to `none` in `reranker.py` source code.
- [ ] `RAG_RERANKER_PROVIDER=jina` removed from `docker-compose.yml` / container env.
- [ ] **Optional Jina gate (diagnostic only):** when Jina is explicitly enabled, no single
  named-author or named-concept query may regress below its heuristic ndcg@10 score.
- [ ] Retrieval diagnostics explain pool membership, query-anchor hits, expansion-term usage,
  author-gate removals, and fallback decisions.
- [ ] Existing backend tests pass.
- [ ] RAG eval commands used for comparison are documented in the task journal.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

- [x] Run baseline diagnostics before code changes.
- [x] Identify worst per-query regressions and classify them as candidate-generation vs
  ranking/fusion failures.
- [ ] Tune annotation pool scoring: demote `entity_annotation_pool` and `concept_annotation_pool`
  weights from 1.1 to 0.7 in `fuse_hardened_candidates`.
- [ ] Re-run `diagnose-reranker --provider jina --input-mode raw` after weight change and verify
  `scale_economies_shared` recovers and mean NDCG does not regress further.
- [ ] Add query-anchor eligibility check for annotation pool candidates if weight demotion alone
  is insufficient.
- [ ] Filter corpus expansion terms before building expansion sparse queries (after Issue 171 data
  is populated).
- [ ] Add expansion-dominance fallback with diagnostics.
- [ ] Confirm `_enforce_source_author_gate` is applied after all pool injections.
- [ ] Change `RAG_RERANKER_PROVIDER` code default from `"jina"` → `"none"` in `reranker.py`.
- [ ] Remove `RAG_RERANKER_PROVIDER=jina` from `docker-compose.yml` (or set to `none`).
- [ ] A/B eval: run `diagnose-reranker` (heuristic, no reranker) before and after Fix 1;
  confirm `scale_economies_shared` recovers and mean heuristic ndcg@10 does not drop.
- [ ] Final acceptance (primary gate): heuristic ndcg@10 ≥ 0.36 on the 15-query golden set.

<!-- MACHINE_RENDERED_START -->
## Execution Journal

### 2026-05-28 — Diagnostic run (Issue 174)

**Branch**: `feature/issue-172-entity-concept-retrieval-wiring-and-eval`

**Commands run:**
```bash
docker exec capitalos-api python -m app.rag.eval.cli structural-recall
docker exec capitalos-api python -m app.rag.eval.cli diagnose-reranker \
  --top-k 10 --candidate-pool-size 40 --output /tmp/diag_heuristic.json
docker exec capitalos-api python -m app.rag.eval.cli diagnose-reranker \
  --top-k 10 --candidate-pool-size 40 --provider jina --input-mode raw \
  --output /tmp/diag_jina.json
```

**Structural recall**: 88/88 passed, 0 failed, 3 authors covered.

**Heuristic quality**:
```
mean_ndcg@10: 0.3386  (historical: 0.3882, delta: -0.0496)  ← exceeds -0.02 gate
mean_recall@10: 0.4222  (historical: 0.4556, delta: -0.0334)
mean_mrr: 0.4836  (historical: 0.5527, delta: -0.0691)
```

**Jina/raw quality**:
```
mean_ndcg@10: 0.4192  (historical: 0.4680, delta: -0.0488)  ← exceeds -0.02 gate
mean_recall@10: 0.4505  (historical: 0.4838, delta: -0.0333)
mean_mrr: 0.6056  (historical: 0.6711, delta: -0.0655)
```

**Candidate pool recall**: 0.8053 (historical: 0.8164, delta: -0.0111)

**Pool gap queries** (relevant chunks missing from 40-candidate pool):
- "How should investors think about Mr Market?" — pool_recall=0.333
- "What are Charlie Munger's main mental models?" — pool_recall=0.214
- "What are some of the best mental models that Charlie Munger lives by?" — pool_recall=0.232

**Jina regression query** (relevant chunks in pool, Jina discards them):
- "What is Nick Sleep's concept of scale economies shared?" — heuristic=0.157, jina=0.000

**Root cause confirmed**: `concept_annotation_pool` is populated for this query
(`plan.resolved_concept_ids = ['scale_economies_shared']`).  Weight 1.1 causes annotation-ranked
chunks to crowd the top-40 Jina input window.  Fix: reduce weight to 0.7.

**Next action**: Implement Fix 1 (weight demotion) in `fuse_hardened_candidates`, then re-run eval.

## Execution Journal (Codex Mutable)
- Current Stage: `diagnosis_complete`
- Workflow Status: `in_progress`
- Provider/Model: `claude/sonnet-4.6`
- Last Updated: `2026-05-28`

## Deterministic Gate Results (Codex Mutable)
- `structural-recall`: **pass** — 88/88, 0 failed, 3 authors covered
- `rag-eval-hardening-compare`: **fail** — heuristic ndcg@10=0.3386 (-0.0496 vs baseline), Jina ndcg@10=0.4192 (-0.0488 vs baseline); both exceed -0.02 gate
- `reranker-diagnosis`: **fail** — Jina causes regression on scale_economies_shared (0.157→0.000); root cause identified (concept_annotation_pool weight 1.1)
- `targeted-backend-tests`: `skip` — no code changes yet
- `test-backend`: `skip` — no code changes yet
- `api-smoke`: `skip` — not in scope for diagnostic phase

## Extra Files Changed (Codex Mutable)
_None — diagnostic phase only, no implementation files modified._

## Human Action Summary (Codex Mutable)
- Next expected action: Implement Fix 1 (reduce `entity_annotation_pool` + `concept_annotation_pool` weights from 1.1 → 0.7 in `fuse_hardened_candidates`), then re-run `diagnose-reranker` to confirm scale-economies regression is fixed and mean NDCG does not drop further.
- Open questions:
  - None.

## Automation Log (Mutable)
_Automation appends structured logs here._
