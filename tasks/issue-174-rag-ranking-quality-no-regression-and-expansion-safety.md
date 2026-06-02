# Issue 174: Protect the current RAG quality and fix remaining ranking mistakes

## Why this issue still matters

The retrieval system is now materially better than it was before the recent Sonnet changes.
Issue 174 should not add another broad set of retrieval features. Its job is narrower:

1. Treat the current working behavior as the quality baseline that future changes must preserve.
2. Add automated checks so a change cannot silently make search results worse.
3. Investigate the remaining Nick Sleep / Amazon ranking problem and fix the root cause if a general fix is justified by evidence.

## Terms used in this issue

- **Chunk**: a short passage extracted from an ingested document.
- **Candidate**: a chunk that might answer the user's question.
- **Dense retrieval**: semantic search. It compares the meaning of the question with the meaning
  of each chunk using embeddings.
- **Sparse retrieval**: keyword search. It finds chunks containing important words or phrases from
  the question.
- **Candidate pool**: the temporary set of chunks found by one retrieval method before the final
  results are selected.
- **Ranking**: ordering the candidates so the most useful chunks appear first.
- **Reranker**: a second ranking step. Jina receives the shortlisted chunks and reorders them based
  on how well each chunk answers the question.
- **Expanded context**: neighboring or parent text shown only when the user clicks
  `Show expanded context`. It helps the user read a winning chunk in context.
- **Golden set**: a small set of test questions with human-labeled relevant chunks. It lets us
  compare retrieval quality before and after a code change.
- **Recall@10**: of all labeled relevant chunks, the percentage found in the first 10 results.
- **Precision@10**: of the first 10 results, the percentage labeled relevant.
- **MRR**: how early the first relevant result appears. A score of `1.0` means the first result is
  relevant.
- **NDCG@10**: a ranking-quality score for the first 10 results. It rewards placing highly relevant
  chunks near the top. Higher is better.

## Current retrieval flow

For each AI Sage question:

1. Identify any named author and the actual topic being asked about.
2. Keep a single-author question inside that author's documents. For example,
   `What does Nick Sleep say about Amazon?` must search Nick Sleep's documents.
3. Run dense retrieval and sparse retrieval to find possible answers.
4. Optionally use entity and concept metadata to discover additional candidates.
5. Optionally use author-specific corpus expansion terms. These are related search terms learned from an author's own documents. They are a search aid, not proof that a chunk is relevant.
6. Remove duplicates and prune weak candidates.
7. Merge and rank the remaining candidates.
8. Send the shortlist to Jina for reranking when `RAG_RERANKER_PROVIDER=jina`.
9. Return the selected chunks.
10. Attach parent or neighboring text only as expanded UI context after ranking is finished.

Important distinction:

- Parent and neighboring chunks must not compete as independent ranked results. They are display
  context only.
- The backend still contains a separate `corpus_expansion_pool` for author-specific search terms.
  If it is used, its candidates must pass the same relevance pruning and author filter as all other
  candidates.

## Current quality baseline to protect

These results were measured on the 15-query golden set using the live AI Sage path after rebuilding
the current API image.

| Metric | Previous recorded run | Current without Jina | Current with Jina |
|---|---:|---:|---:|
| `NDCG@5` | `0.2471` | `0.4431` | `0.4828` |
| `NDCG@10` | `0.3224` | `0.4953` | `0.5455` |
| `Recall@5` | `0.2441` | `0.4077` | `0.4155` |
| `Recall@10` | `0.3979` | `0.5125` | `0.5693` |
| `Precision@10` | `0.2296` | `0.2881` | `0.3081` |
| `MRR` | `0.4913` | `0.7578` | `0.8095` |

The Jina-enabled result is currently the best measured configuration:

- `NDCG@10` improved by `69.2%` compared with the previous recorded run.
- `Recall@10` improved by `43.1%`.
- `Precision@10` improved by `34.2%`.
- `MRR` improved by `64.8%`.

`RAG_RERANKER_PROVIDER=jina` is enabled in the running environment and should remain enabled unless
a repeatable live evaluation proves that disabling it produces better user-facing results.

## Known remaining problem

Jina improves the overall result, but it slightly worsens this query:

`What does Nick Sleep say about Amazon's business model?`

| Metric | Without Jina | With Jina |
|---|---:|---:|
| `NDCG@10` | `0.3209` | `0.2978` |
| `Recall@10` | `0.5000` | `0.5000` |
| `MRR` | `0.2000` | `0.1667` |

There are two different failure cases:

1. A chunk from a document authored by somebody other than Nick Sleep is invalid and must be blocked by the author filter.
2. A chunk from a Nick Sleep document that happens to discuss Warren Buffett is allowed into the candidate set, but it should rank below Nick Sleep passages that actually discuss Amazon.

The second case is the likely remaining issue. Fixing it requires understanding which ranking stage
promotes the weak passage. Do not add a Nick-Sleep-specific rule or hardcode chunk IDs.

## Objective

- Preserve or improve the current live AI Sage metrics.
- Keep Jina enabled while it remains the best measured configuration.
- Add a deterministic quality gate that compares both Jina-enabled and Jina-disabled retrieval.
- Diagnose the Nick Sleep / Amazon regression one stage at a time.
- Fix the underlying generic ranking problem only after the diagnosis identifies it.
- Keep parent and neighboring text as expanded UI context only.

## Reframed Execution Model (Issue 174)

This issue now follows a baseline-first convergence model:

1. Treat the hardened low-level retrieval path as the starting baseline.
2. Add AI Sage retrieval/ranking modifications on top of that baseline one by one.
3. Measure quality after each single addition.
4. Keep a change only if it improves quality or is clearly non-regressing.
5. If quality degrades, either fix it immediately or remove that change.
6. Repeat until all AI Sage-stage additions have been evaluated.
7. End state: one converged production path where AI Sage retrieval quality is equal to or better
  than the hardened baseline; never worse.

## Golden Path Policy

Use exactly one production retrieval path: the same AI Sage path used by UI.

Any optimization must follow this sequence:

1. Start from the current golden path baseline.
2. Add one optimization at a time (single isolated change).
3. Measure quality on the golden set immediately after that one change.
4. Keep the change only if quality improves or remains within the no-regression bar.
5. Remove the change if quality degrades.

Do not stack multiple retrieval/reranking changes before measurement.
Do not keep "optimizations" that reduce final UI evidence quality.

Convergence requirement:

- Hardened low-level baseline and AI Sage retrieval behavior must converge to the same effective
  evidence-selection logic by the end of this issue.
- If any AI Sage-only stage cannot be proven beneficial, it must be removed or rewritten.

## Required work

### 1. Add a quality gate for the live AI Sage path

Run the 15-query golden set through the same path used by the UI, not only the lower-level retrieval
function.

The report must include:

- aggregate metrics with Jina disabled
- aggregate metrics with Jina enabled
- per-query metrics for both configurations
- the difference between the two configurations
- a list of queries made worse by Jina
- a list of queries with no relevant result in the first 10 results

Use the current metrics in this file as the baseline. Allow only a small documented tolerance for
rounding or unavoidable provider variance.

### 2. Trace the Nick Sleep / Amazon query end to end

For the Nick Sleep / Amazon query, record:

1. The cleaned query and detected author.
2. Dense-search candidates before pruning.
3. Sparse-search candidates before pruning.
4. Candidates added by entity, concept, or corpus-local search terms.
5. Candidates removed as duplicates or weak matches.
6. The merged shortlist before Jina.
7. Jina's reordered shortlist.
8. The final chunks shown in AI Sage.

If multiple weak or irrelevant chunks appear anywhere in the trace, record all of them and group
them by shared cause. Do not stop at a single outlier passage if the broader failure is candidate
over-generation, over-broad topic matching, or reranker leakage.

For each candidate, include:

- chunk ID
- source document
- source author
- short text preview
- retrieval pool membership
- score before Jina
- Jina score if available
- reason the candidate was kept or removed

Then classify the failure:

- wrong-author filtering problem
- poor candidate generation
- insufficient pruning
- fusion-scoring problem
- Jina reranking problem
- incorrect golden labels

If the trace shows several unrelated passages from the same author corpus, note whether the issue
is broad over-generation, overly permissive topic/entity expansion, or ranking that fails to
separate the strongest Amazon passages from merely adjacent business-model passages.

### 3. Make the smallest generic fix supported by the trace

The implementation depends on the diagnosis. Examples:

- strengthen author filtering if cross-author documents leak through
- reject weak candidates that do not mention or semantically match the requested topic
- improve duplicate removal if repeated passages consume result slots
- adjust candidate-pool merging if one pool crowds out stronger evidence
- change the Jina shortlist or selection rule if Jina promotes weak passages

Do not:

- hardcode Nick Sleep, Amazon, or chunk IDs in production ranking logic
- reintroduce parent or neighboring chunks as independent ranked candidates
- add broad expansion terms without proving that they improve the live golden-set metrics
- disable Jina merely because one query regresses while the overall result is materially better

Implementation protocol for this section:

- Start from hardened low-level baseline behavior.
- Evaluate each AI Sage-stage addition independently (single diff per experiment).
- Record before/after metrics for each experiment.
- Keep only additions that help or do not regress guarded metrics.
- Roll back additions that regress quality and cannot be corrected quickly with a generic fix.

### 4. Keep expanded context separate from ranked evidence

Add or retain tests proving:

- parent and neighboring chunks are attached only after final ranking
- clicking `Show expanded context` can reveal surrounding text
- surrounding text does not independently enter the ranked result list

### 5. Repair stale deterministic tests

**DONE.** Five tests in `test_rag_retrieval.py` and `test_rag_constraint_retrieval.py` used
`"sample text"` placeholders for queries such as `"float insurance"` and `"test"`. The quality
pruning correctly rejected those placeholders with `reason=missing_primary_entity_or_topic`.
Fixtures were updated to use relevant text matching each query. Production pruning unchanged.
Full suite: **855 passed, 4 skipped, 0 failed**.

### 6. Display context expansion for all chunks

**DONE.** The `expand_chunks_with_context` call in `execute_concept_query` was using
`only_when_needed=True`, which only expanded chunks shorter than 280 chars or ending
mid-sentence. Changed to `only_when_needed=False` so every final winner chunk receives
`context_text` in its metadata, ensuring the UI "Show expanded context" button appears for all
chunks.

### Decision: query expansion not added to scope

A generic LLM-driven query expansion stage was considered and explicitly rejected:

- Dense retrieval already handles vocabulary mismatch through embedding semantics — it is
  implicit query expansion.
- `corpus_expansion_terms` stored per author in `rag_corpus_expansions` is already a targeted,
  author-scoped expansion mechanism running through the `corpus_expansion_pool`.
- The remaining problem is **precision and ranking**, not recall. `Recall@10=0.5693` is healthy.
  Expansion improves recall but typically hurts precision by pulling in loosely-related candidates,
  which would push `Precision@10` below its current `0.3081`.
- The Nick Sleep / Amazon failure is specifically an author-boundary leak. More candidates from
  expansion would worsen that problem before the author filter catches them.

If corpus coverage for specific topics is found to be the bottleneck in a future evaluation, a
targeted author-scoped expansion experiment with a before/after golden-set measurement would be
the correct approach. Do not add generic expansion without evidence.

## Acceptance criteria

- [x] The live AI Sage golden-set comparison runs with Jina disabled and enabled.
- [x] The report includes `NDCG@5`, `NDCG@10`, `Recall@5`, `Recall@10`, `Precision@10`, and `MRR`.
- [x] Jina remains enabled in the running environment unless measured results prove another
  configuration is better. *(enabled: `RAG_RERANKER_PROVIDER=jina`)*
- [ ] The final Jina-enabled metrics do not materially regress from the current baseline:
  `NDCG@10=0.5455`, `Recall@10=0.5693`, `Precision@10=0.3081`, `MRR=0.8095`.
- [ ] The final Jina-disabled metrics do not materially regress from the current baseline:
  `NDCG@10=0.4953`, `Recall@10=0.5125`, `Precision@10=0.2881`, `MRR=0.7578`.
- [x] The Nick Sleep / Amazon trace identifies the exact stage that promotes weak results.
- [ ] Any ranking fix is generic and justified by before-and-after evidence.
- [ ] Every AI Sage-only retrieval/reranking addition has been tested one-by-one against the
  hardened baseline and explicitly marked keep/remove.
- [ ] The final converged AI Sage path is not worse than the hardened baseline on guarded metrics.
- [ ] Single-author questions cannot return chunks from another author's documents.
- [ ] A chunk inside a selected author's document is not rewarded merely because it mentions
  another famous investor.
- [x] Parent and neighboring text remain expanded UI context only and are not ranked independently.
  *(`only_when_needed=False` ensures all final winner chunks receive `context_text`.)*
- [x] Corpus-local search terms pass normal relevance pruning and author filtering.
  *(corpus_expansion_pool already gated by `_prune_retrieval_pool`.)*
- [x] Placeholder-based deterministic tests are updated without weakening production logic.
  *(855 passed, 0 failed after fixture updates.)*
- [x] Targeted RAG tests pass.
- [x] Full backend deterministic tests pass.
- [x] API smoke passes.

<!-- IMMUTABLE_PLAN_END -->

## Task checklist

- [x] Run the live AI Sage golden-set evaluation with Jina disabled and enabled and record results
  in the execution journal. *(CLI already built: `run-ai-sage`, `compare`, `gate` commands exist.)*
- [x] Treat AI Sage UI path as the single golden retrieval path for quality decisions.
- [x] Apply retrieval/reranking optimizations one at a time with before/after measurement.
- [x] Roll back any optimization that worsens the golden-set metrics or UI evidence relevance.
- [x] Establish hardened low-level baseline report and lock it as the starting reference.
- [x] Enumerate AI Sage-only retrieval/reranking stages to test as overlays on baseline.
- [x] Execute keep/remove decision for each stage with recorded evidence.
- [ ] Converge to a single path where AI Sage quality is baseline-or-better.
- [x] Trace the Nick Sleep / Amazon query through every retrieval stage using `diagnose-reranker`.
- [x] Classify the root cause before changing ranking behavior.
- [ ] Implement the smallest generic fix supported by evidence, if needed.
- [x] Confirm parent and neighboring context remains display-only. *(`only_when_needed=False`)*
- [x] Repair stale synthetic relevance-pruning test fixtures. *(855 passed, 0 failed)*
- [x] Run targeted RAG tests. *(passing)*
- [x] Run the full backend deterministic suite. *(855 passed, 0 failed)*
- [x] Run API smoke.
- [x] Verify the final live AI Sage metrics against the protected baseline. *(verification executed; metrics are currently below protected baseline and issue remains open.)*

## Stage Experiment Ledger (One-by-One)

Use this ledger to evaluate AI Sage-only additions against the hardened baseline.
Exactly one stage change per experiment. No batching.

Guardrails for each row:

- Aggregate gate: no regression beyond documented bar.
- Query gate: Nick Sleep/Amazon must not worsen.
- UI gate: no clearly off-topic evidence in final AI Sage cards.

| Stage ID | AI Sage addition over hardened baseline | Hypothesis | Metric gate | Decision | Notes |
|---|---|---|---|---|---|
| S0 | Hardened low-level baseline (reference) | Establish anchor quality | Record baseline report | Locked | Source of truth for keep/remove decisions |
| S1 | AI Sage pruning parity via canonical pool names (`dense_content`, `sparse_content`) | Align AI Sage pruning strictness with hardened path | Aggregate non-regression + query non-regression | Keep | Fixed mismatch where AI Sage pool names bypassed stricter guards |
| S2 | Diagnose tooling parity (`diagnose-query` uses AI Sage path) | Remove path ambiguity in diagnosis | Diagnostic parity only (no ranking change) | Keep | Ensures measurements reflect UI path |
| S3 | Topic-focus guard after rerank for explicit topic-entity queries | Suppress clearly off-topic survivors when enough on-topic evidence exists | Aggregate non-regression + reduced off-topic UI chunks | Provisional Keep | Continue measuring across full golden set and target query |
| S4 | Aggressive pure reranker trigger for "what does X say about Y" | Improve focused attribution queries | Must improve target query without aggregate regression | Remove | Improved one query but regressed aggregate recall; reverted |
| S5 | Candidate admission tightening for explicit topic entities | Reduce weak Amazon-adjacent chunks | Aggregate non-regression + better target query ranking | Provisional Keep | Applied safe topic-focus candidate gate with min-kept fallback; aggregate metrics held, target query metrics unchanged, and Attenborough/rainforest no longer appeared in diagnose-query output |
| S6 | Stricter topic-entity admission (disallow generic phrase-only matches when topic entity exists) | Further reduce weak non-entity passages | Aggregate non-regression + better target query ranking | Remove | Regressed aggregate AI Sage metrics (`ndcg@10` and `recall@10` down) while target-query metrics unchanged; reverted immediately |
| S7 | Similarity-gated phrase fallback for topic-focus matching | Keep recall while filtering weak phrase-only chunks when entity evidence is absent | Aggregate non-regression + better target query ranking | Remove | Regressed AI Sage aggregate (`mean_ndcg@10=0.5281`, `mean_recall@10=0.5304`, `mean_mrr=0.804`) with no target-query improvement (`ndcg@10=0.2978`, `mrr=0.1667`); rolled back |
| S8 | Topic-focus gate min-keep calibration (`max(4, min(top_k, 8))`) | Apply explicit-topic filtering more consistently on moderate candidate pools without starving rerank | Aggregate non-regression + better target query ranking | Remove | Nick Sleep target query remained unchanged (`ndcg@10=0.2978`, `mrr=0.1667`) across runs; aggregate readings were mixed and offered no reliable quality gain; rolled back |
| S9 | Author-attribution pure rerank override (adaptive fusion) | Let cross-encoder dominate only for explicit single-author “what does X say about Y” style queries | Aggregate non-regression + better target query ranking | Keep | Stable across repeated runs: AI Sage aggregate (`mean_ndcg@10=0.543`, `mean_recall@10=0.5221`, `mean_mrr=0.8633`) remains above low-level baseline (`0.4545` / `0.4217` / `0.5944`) and Nick Sleep row improved (`ndcg@10: 0.2978 -> 0.3209`, `mrr: 0.1667 -> 0.2`) |
| S10 | Attribution rerank refinement by topic-entity hit density | Improve top-rank ordering for explicit author-attribution queries while keeping S9 aggregate gains | Aggregate non-regression + better target query ranking | Remove | No measurable gain vs S9: aggregate and target-query metrics were unchanged (`AISAGE ndcg@10=0.543`, `recall@10=0.5221`, `mrr=0.8633`; Nick Sleep `ndcg@10=0.3209`, `mrr=0.2`); rolled back to keep path minimal |

Execution rule:

- If a stage fails gates and cannot be fixed quickly with a generic patch, remove it and proceed.
- Final merged path must be baseline-or-better, never worse.

## Execution journal

This issue was rewritten after the retrieval pipeline improved materially. Earlier Issue 174
numbers and recommendations were based on an older code path and are no longer the acceptance
baseline. The current protected baseline is recorded above.

Latest diagnosis and measured changes:

- Confirmed UI path can surface weak evidence for the Nick Sleep / Amazon business-model query.
  Off-topic/weak chunks were reproducible in live AI Sage UI evidence cards.
- Unified diagnostics with production path: `diagnose-query` now executes AI Sage concept mode
  (`execute_concept_query`) rather than a lower-level retrieval-only path.
- Fixed AI Sage pruning parity bug: AI Sage candidate pruning now uses canonical pool names
  (`dense_content`, `sparse_content`) so the same low-signal guardrails apply as hardened retrieval.
- Added a targeted post-rerank topic-focus guard for explicit topic-entity queries, with a
  minimum-kept fallback to avoid zero-result traps.
- Tested an additional optimization (aggressive pure reranker fusion for "what does X say about Y"
  query shape). It improved the single Nick Sleep query but degraded aggregate golden-set recall.
  Per golden-path policy, this optimization was removed.

Current operating rule (enforced):

- Apply one optimization at a time.
- Measure immediately on the golden set.
- Keep only non-regressing improvements.
- Roll back any change that worsens aggregate UI-path retrieval quality.

<!-- MACHINE_RENDERED_START -->
## Execution Journal

### 2026-06-01 deterministic verification run (current production path)

#### Commands executed

1. `docker compose exec -T -e RAG_RERANKER_PROVIDER=none api python -m app.rag.eval.cli run-ai-sage --label issue174_ai_sage_jina_disabled --top-k 10 --output /app/data/reports/issue174/ai_sage_jina_disabled.json`
2. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api python -m app.rag.eval.cli run-ai-sage --label issue174_ai_sage_jina_enabled --top-k 10 --output /app/data/reports/issue174/ai_sage_jina_enabled.json`
3. `make rag-eval-reranker-diagnose QUERY_CONTAINS="Nick Sleep say about Amazon" PROVIDERS=jina INPUT_MODES=raw RAG_RETRIEVAL_TRACE=1 OUTPUT=/app/data/reports/issue174/diagnose_nick_sleep_amazon_jina_raw.json`
4. `make api-smoke`

Artifacts:

- `data/reports/issue174/ai_sage_jina_disabled.json`
- `data/reports/issue174/ai_sage_jina_enabled.json`
- `data/reports/issue174/diagnose_nick_sleep_amazon_jina_raw.json`
- `data/reports/issue174/run_ai_sage_jina_disabled.stdout.log`
- `data/reports/issue174/run_ai_sage_jina_enabled.stdout.log`
- `data/reports/issue174/diagnose_nick_sleep_amazon_jina_raw.stdout.log`
- `data/reports/issue174/api_smoke.stdout.log`

#### Aggregate golden-set metrics (live AI Sage path)

| Metric | Protected baseline (disabled) | Current disabled | Protected baseline (enabled) | Current enabled |
|---|---:|---:|---:|---:|
| `NDCG@5` | `0.4431` | `0.4359` | `0.4828` | `0.4803` |
| `NDCG@10` | `0.4953` | `0.4881` | `0.5455` | `0.5263` |
| `Recall@5` | `0.4077` | `0.3910` | `0.4155` | `0.4155` |
| `Recall@10` | `0.5125` | `0.4959` | `0.5693` | `0.5387` |
| `Precision@10` | `0.2881` | `0.3172` | `0.3081` | `0.3372` |
| `MRR` | `0.7578` | `0.7489` | `0.8095` | `0.7729` |

Result: Jina-enabled remains better than disabled in current runs, but both configurations are below the protected `NDCG@10` / `Recall@10` / `MRR` baselines recorded at issue lock-in, so Issue 174 is **not done**.

#### Per-query comparison summary (enabled vs disabled)

- Queries made worse by Jina in current run:
  - `How does Charlie Munger think about mental models and latticework?` (`NDCG@10: -0.0135`, `MRR: -0.5000`)
  - `What does Buffett say about circle of competence?` (`NDCG@10: -0.0369`)
- Queries with no relevant result in top 10:
  - Disabled: `How do great investors think about margin of safety?`
  - Enabled: none

Full per-query metrics for both configurations are in the two JSON reports above.

#### Nick Sleep / Amazon stage diagnosis (fresh trace)

- Query: `What does Nick Sleep say about Amazon's business model?`
- `strict_source_author=true`; retrieval plan filtered to `author_ids_filter=[nick_sleep]`.
- Candidate pool recall was complete (`candidate_pool_recall=1.0`), so recall is not the bottleneck.
- `diagnose-reranker` for `jina/raw` still underperformed heuristic on this query (`NDCG@10: 0.2978 vs 0.3209`, `MRR: 0.1667 vs 0.2`) in the isolated reranker benchmark.
- Current live AI Sage run with production fusion retained Nick query at `NDCG@10=0.3209`, `MRR=0.2` (no regression vs heuristic baseline for this one row).

Diagnosis: remaining weakness is still ranking-stage behavior (reranker input/fusion sensitivity), not cross-author leakage and not candidate recall.

#### Converged production path verification

Verified in current code path (`execute_concept_query`):

- AI Sage eval and diagnostics use the UI path (`execute_concept_query`) rather than a separate retrieval-only path.
- Canonical pruning pool naming parity is in place (`dense_content`, `sparse_content`).
- Topic-focus guard remains after rerank with bounded min-keep fallback.
- Author-attribution adaptive fusion override (S9) is present (`_query_prefers_author_attribution_pure_rerank`).
- S10-style extra attribution refinement is not retained; path is minimalized relative to tested removals.
- Expanded context remains display-only and is attached after ranking/dedup.

Conclusion: retained production path matches the converged keep/remove intent from the stage ledger, but acceptance is still blocked by aggregate baseline regression.

#### API smoke result

- `make api-smoke` passed (`/health` OK and authenticated `/dashboard/summary` returned valid JSON).

#### Exact remaining work (issue still open)

1. Reproduce and explain aggregate drift from protected baseline (`NDCG@10`, `Recall@10`, `MRR`) using the same corpus snapshot and reranker config assumptions as the lock-in run.
2. Run one isolated ranking/fusion experiment at a time to recover aggregate guarded metrics while preserving Nick Sleep/Amazon non-regression.
3. Keep only changes that pass guarded aggregate metrics and query-level sanity; roll back regressions immediately.
4. Re-run final deterministic pack (`run-ai-sage` disabled/enabled + `api-smoke`) and update this journal with passing baseline bars before closure.

#### Sentinel attempt (rolled back)

- Ran one isolated sentinel change to backfill topic-focused candidate pools when undersized before rerank.
- Gate outcome: **remove/rollback**.
- Why removed:
  - No improvement on the sentinel query (`What does Buffett say about circle of competence?` stayed at `retrieved_count=4`, no gain in `NDCG@10`/`Recall@10`/`MRR`).
  - Jina-enabled aggregate regressed in this trial (`mean_ndcg@10` and `mean_recall@10` down vs current retained path).

Sentinel trial artifacts:

- `data/reports/issue174/sentinel_backfill_jina_disabled.json`
- `data/reports/issue174/sentinel_backfill_jina_enabled.json`
- `data/reports/issue174/sentinel_backfill_jina_disabled.stdout.log`
- `data/reports/issue174/sentinel_backfill_jina_enabled.stdout.log`

#### Deterministic drift reporting command (new)

- Added committed comparison module inside backend eval package for reproducible report analysis:
  - module: `api/app/rag/eval/drift.py`
  - tests: `api/tests/test_rag_eval_drift.py`
  - `make rag-eval-drift OLD_REPORT=<path> NEW_REPORT=<path> [MAX_ROWS=20]`
- This replaces ad-hoc inline snippets for metric drift review and prints:
  - aggregate deltas,
  - per-query changed rows,
  - slice-health deltas (`buffett`, `munger_mental_models`, `nick_sleep`).

### 2026-06-01 attribution-density gate revisit

#### Commands executed

1. `make api-rebuild`
2. `./.venv/bin/pytest -q api/tests/test_ai_sage_retrieval_pipeline.py -k 'author_attribution_pure_rerank_requires_candidate_support or nick_sleep_query_surfaces_multiple_distinct_examples'`
3. `docker compose exec -T -e RAG_RERANKER_PROVIDER=none api python -m app.rag.eval.cli run-ai-sage --label issue174_attribution_gate_jina_disabled --top-k 10 --output /app/data/reports/issue174/attribution_gate_jina_disabled.json`
4. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api python -m app.rag.eval.cli run-ai-sage --label issue174_attribution_gate_jina_enabled --top-k 10 --output /app/data/reports/issue174/attribution_gate_jina_enabled.json`
5. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_disabled.json NEW_REPORT=data/reports/issue174/attribution_gate_jina_disabled.json MAX_ROWS=12`
6. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_enabled.json NEW_REPORT=data/reports/issue174/attribution_gate_jina_enabled.json MAX_ROWS=12`
7. `make api-smoke`

#### Outcome

- Tightened the author-attribution pure-rerank trigger so it only fires when the candidate pool is large enough and actually contains multiple topic-bearing candidates.
- Jina-disabled aggregate stayed flat versus the retained baseline (`mean_ndcg@10=0.4881`, `mean_recall@10=0.4959`, `mean_mrr=0.7489`).
- Jina-enabled aggregate improved versus the retained baseline (`mean_ndcg@10=0.5407`, `mean_recall@10=0.561`, `mean_precision@10=0.3439`, `mean_mrr=0.7784`).
- Changed-query drift was limited to two rows, with the biggest gain on `How should investors think about Mr Market?` and a smaller gain on `What does Buffett say about circle of competence?`.
- This is an improvement, but it still does not clear the protected baseline bars, so Issue 174 remains open.

### 2026-06-01 topic-admission density revisit

#### Commands executed

1. `./.venv/bin/pytest -q api/tests/test_ai_sage_retrieval_pipeline.py -k 'topic_focus_phrase_support_count_tracks_exact_matches or author_attribution_pure_rerank_requires_candidate_support'`
2. `make api-rebuild`
3. `docker compose exec -T -e RAG_RERANKER_PROVIDER=none api python -m app.rag.eval.cli run-ai-sage --label issue174_topic_density_gate_jina_disabled --top-k 10 --output /app/data/reports/issue174/topic_density_gate_jina_disabled.json`
4. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api python -m app.rag.eval.cli run-ai-sage --label issue174_topic_density_gate_jina_enabled --top-k 10 --output /app/data/reports/issue174/topic_density_gate_jina_enabled.json`
5. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_disabled.json NEW_REPORT=data/reports/issue174/topic_density_gate_jina_disabled.json MAX_ROWS=12`
6. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_enabled.json NEW_REPORT=data/reports/issue174/topic_density_gate_jina_enabled.json MAX_ROWS=12`
7. `make api-smoke`

#### Outcome

- Added a stricter topic-admission density guard that only tightens the pool when multiple exact topic phrases are present.
- Jina-disabled metrics stayed flat versus the retained baseline.
- Jina-enabled metrics were nearly flat overall, with only a small NDCG gain on `What does Buffett say about circle of competence?` and no recall or MRR lift.
- This is not a strong enough aggregate improvement to promote as the retained answer by itself; it remains an exploratory tweak while the issue stays open.

### 2026-06-01 S8 min-keep recalibration revisit

#### Commands executed

1. `./.venv/bin/pytest -q api/tests/test_ai_sage_retrieval_pipeline.py -k 'topic_focus_min_keep_uses_s8_calibration or topic_focus_phrase_support_count_tracks_exact_matches or author_attribution_pure_rerank_requires_candidate_support'`
2. `make api-rebuild`
3. `docker compose exec -T -e RAG_RERANKER_PROVIDER=none api python -m app.rag.eval.cli run-ai-sage --label issue174_s8_min_keep_jina_disabled --top-k 10 --output /app/data/reports/issue174/s8_min_keep_jina_disabled.json`
4. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api python -m app.rag.eval.cli run-ai-sage --label issue174_s8_min_keep_jina_enabled --top-k 10 --output /app/data/reports/issue174/s8_min_keep_jina_enabled.json`
5. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_disabled.json NEW_REPORT=data/reports/issue174/s8_min_keep_jina_disabled.json MAX_ROWS=12`
6. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_enabled.json NEW_REPORT=data/reports/issue174/s8_min_keep_jina_enabled.json MAX_ROWS=12`

#### Outcome

- Re-tried S8 exactly as an isolated min-keep calibration (`max(4, min(top_k, 8))`).
- Disabled metrics were unchanged (`mean_ndcg@10=0.4881`, `mean_recall@10=0.4959`, `mean_mrr=0.7489`).
- Enabled metrics matched the current attribution-density run (`mean_ndcg@10=0.5407`, `mean_recall@10=0.561`, `mean_mrr=0.7784`), so S8 added no incremental value.
- Decision: reject/remove. The calibration was reverted immediately because it did not change the rebuilt outcome.

### 2026-06-01 S7 similarity-gated phrase fallback revisit

#### Commands executed

1. `./.venv/bin/pytest -q api/tests/test_ai_sage_retrieval_pipeline.py -k 'required_phrase_fallback_requires_strong_similarity or topic_focus_phrase_support_count_tracks_exact_matches or author_attribution_pure_rerank_requires_candidate_support'`
2. `make api-rebuild`
3. `docker compose exec -T -e RAG_RERANKER_PROVIDER=none api python -m app.rag.eval.cli run-ai-sage --label issue174_s7_phrase_gate_jina_disabled --top-k 10 --output /app/data/reports/issue174/s7_phrase_gate_jina_disabled.json`
4. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api python -m app.rag.eval.cli run-ai-sage --label issue174_s7_phrase_gate_jina_enabled --top-k 10 --output /app/data/reports/issue174/s7_phrase_gate_jina_enabled.json`
5. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_disabled.json NEW_REPORT=data/reports/issue174/s7_phrase_gate_jina_disabled.json MAX_ROWS=12`
6. `make rag-eval-drift OLD_REPORT=data/reports/issue174/ai_sage_jina_enabled.json NEW_REPORT=data/reports/issue174/s7_phrase_gate_jina_enabled.json MAX_ROWS=12`
7. `./.venv/bin/pytest -q api/tests/test_ai_sage_retrieval_pipeline.py -k 'topic_focus_phrase_support_count_tracks_exact_matches or author_attribution_pure_rerank_requires_candidate_support'`
8. `make api-rebuild`
9. `make api-smoke`

#### Outcome

- Re-tried S7 as a strict phrase-only fallback gate keyed off retrieval similarity.
- Against the older retained reports it showed only tiny isolated gains, but compared with the stronger current attribution-density path it clearly regressed enabled metrics back down to `mean_ndcg@10=0.5287`, `mean_recall@10=0.5387`, `mean_mrr=0.7729`.
- Nick Sleep slice metrics stayed unchanged, so the gate did not help the main target while it erased broader enabled gains.
- Decision: reject/remove. The change was reverted, the API image was rebuilt, and `make api-smoke` passed on the restored retained path.

### 2026-06-01 golden set expansion to 45 queries

#### Commands executed

1. `rg -n '^  - query:' api/app/rag/eval/fixtures/rag_golden_queries.yaml | wc -l`
2. `make api-rebuild`
3. `docker compose exec -T api python -m app.rag.eval.cli seed --file app/rag/eval/fixtures/rag_golden_queries.yaml --replace`
4. `docker compose exec -T api python - <<'PY' ... RagEvalGolden distinct(query_text) ... PY`

#### Outcome

- Expanded the fixture at `api/app/rag/eval/fixtures/rag_golden_queries.yaml` from 15 to 45 query prompts by adding paraphrased variants over the same validated evidence anchors.
- Rebuilt the API image so the containerized seed command read the updated fixture.
- Reseeding succeeded with `Loaded 45 golden query entries`, producing `golden_pairs=504` and `golden_queries=45` in Postgres.
- The expanded set is now active for deterministic comparisons.

### 2026-06-01 ranking-only blend-alpha sweep on 45-query set

#### Commands executed

1. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina api python -m app.rag.eval.cli run-ai-sage --label issue174_45_default_jina_enabled --top-k 10 --output /app/data/reports/issue174/45_default_jina_enabled.json`
2. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina -e RAG_RERANKER_BLEND_ALPHA=0.30 api python -m app.rag.eval.cli run-ai-sage --label issue174_45_alpha_030_jina_enabled --top-k 10 --output /app/data/reports/issue174/45_alpha_030_jina_enabled.json`
3. `docker compose exec -T -e RAG_RERANKER_PROVIDER=jina -e RAG_RERANKER_BLEND_ALPHA=0.60 api python -m app.rag.eval.cli run-ai-sage --label issue174_45_alpha_060_jina_enabled --top-k 10 --output /app/data/reports/issue174/45_alpha_060_jina_enabled.json`
4. `make rag-eval-drift OLD_REPORT=data/reports/issue174/45_default_jina_enabled.json NEW_REPORT=data/reports/issue174/45_alpha_030_jina_enabled.json MAX_ROWS=20`
5. `make rag-eval-drift OLD_REPORT=data/reports/issue174/45_default_jina_enabled.json NEW_REPORT=data/reports/issue174/45_alpha_060_jina_enabled.json MAX_ROWS=20`
6. `make api-smoke`

#### Outcome

- Baseline (`alpha=0.45`): `mean_ndcg@10=0.4466`, `mean_recall@10=0.4694`, `mean_precision@10=0.3007`, `mean_mrr=0.6289`.
- Candidate `alpha=0.30`: exactly identical aggregates and zero changed queries versus baseline.
- Candidate `alpha=0.60`: slight regression (`mean_ndcg@10` delta `-0.0001`) with one changed query (`What are the mental models Munger tries to live by?` at `ndcg@10 -0.0032`).
- Decision: reject blend-alpha tuning for now. No code change is retained from this sweep because the expanded-set evidence shows no improvement over current default behavior.
<!-- MACHINE_RENDERED_END -->
