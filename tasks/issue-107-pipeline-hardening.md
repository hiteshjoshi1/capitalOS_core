# Issue 107: Pipeline Hardening

## Objective
- Harden the local AI orchestration pipeline (`prepare → plan → build → review → rework → ship`) for reliability, cost efficiency, and maintainability.
- Externalize model configuration, add prompt caching/compaction, integrate optional Context7 MCP, and update documentation — all without regressing existing guardrails.
- Local-first on macOS; no CI dependency; backward-compatible command UX.

## Architecture Decisions

### AD-1: Externalized model config in `.ai-models.env`
Create `.ai-models.env` at repo root (shell-sourceable KEY=VALUE format). Committed to version control with sensible defaults. `task_flow.sh` sources it early with `set -a; source .ai-models.env; set +a`, then applies per-variable validation. Environment variables still override file values (existing behavior preserved). A new function `load_model_config()` validates all model IDs are non-empty and prints the active routing table on `--verbose`.

**Rationale:** Shell env format is the simplest option that requires zero new dependencies, is diffable in git, and maintains the existing override-via-env pattern.

**Tradeoff:** No schema enforcement beyond the validation function. Accepted because the variable set is small and stable.

### AD-2: Model routing remains Opus/Sonnet/Opus with configurable overrides
Default routing stays: `PLAN_MODEL=claude-opus-4.6`, `BUILD_MODEL=codex` (unchanged, not in config — Codex is invoked differently), `REVIEW_MODEL=claude-sonnet-4.6`, `REVIEW_ESCALATION_MODEL=claude-opus-4.6`. A new `CODEX_TIMEOUT_MINUTES` moves into the config file. No model IDs remain hardcoded in logic branches — all references go through the config variables.

**Rationale:** Current routing is already well-tuned. The value is in making it configurable, not changing defaults.

### AD-3: Optional Context7 MCP for plan and review phases
Add `CONTEXT7_ENABLED=0` (off by default) to `.ai-models.env`. When enabled, plan and review phases include `--allow-tool context7` instead of unconditionally denying all MCP tools. A preflight check (`context7_available()`) verifies the MCP server responds; if it fails, the phase continues without Context7 and logs a warning. Setup requires manual user action documented in README.

**Rationale:** Context7 provides up-to-date framework/library docs which improve plan quality, but it is not universally installed. Opt-in with graceful degradation avoids breaking existing users.

**Tradeoff:** When enabled, plan/review phases are non-deterministic with respect to external doc fetches. Documented as acceptable because the human gate still governs plan approval.

### AD-4: Prompt compaction via section stripping
New function `compact_task_context()` strips mutable sections (Automation Log, Retry Log, Verification Evidence, Implementation Reasoning Addendum) from the task file content before sending to plan/review models. Only the immutable plan + Task Checklist + Review Findings (latest cycle only) are sent. Original file is never modified — compaction operates on the string passed to the model.

**Rationale:** Mutable sections accumulate tokens across cycles but carry no decision-relevant information for planning or reviewing. Stripping them reduces cost by ~30-50% of task file tokens in later cycles.

**Tradeoff:** If a reviewer needs to reference prior retry history, they lose that context. Mitigated by keeping Review Findings (which summarize issues) and by the fact that retry details are rarely decision-relevant for the model.

### AD-5: Prompt result caching keyed by content hash
Cache directory: `.task-cache/` (gitignored). Cache key: `sha256(phase + model + compact_task_content + git_tree_hash)`. Cache stores the model's output as a plain text file at `.task-cache/<key>.txt` with a sidecar `.task-cache/<key>.meta` (JSON: timestamp, model, phase, git ref, task file path). Cache is read-through: if key exists, output is reused and a `[CACHE HIT]` log line is emitted. Cache is bypassed with `NO_CACHE=1` env var. Cache applies only to `plan` and `review` phases (build/rework are always live because they modify code).

**Invalidation safety:** The git tree hash changes on any code change; the compact task content hash changes on any task file edit. Together these prevent stale reuse. The cache has no TTL — staleness is structurally impossible given the key composition.

**Rationale:** Plan and review are the most expensive phases (Opus). Caching avoids re-running identical requests during development iteration (e.g., re-running after a failed build that didn't change the plan).

**Tradeoff:** Cache files accumulate on disk. Mitigated by `make task-cache-clean` target and small per-file size (~10-50KB).

### AD-6: No changes to build, rework, ship, or prepare phases
These phases are already reliable and well-guarded. Hardening is scoped to config loading, plan, and review. Verification suite and Codex fix loops are untouched.

### AD-7: Rollback plan
All changes are in 4 files (+ 2 new files). Rollback: `git checkout main -- scripts/task_flow.sh docs/workflows/ai-task-flow.md ReadMe.md Makefile && rm -f .ai-models.env .gitignore-additions`. Cache dir `.task-cache/` can be deleted without consequence.

## Risks
| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| R1 | Config file sourcing order breaks env overrides | Model routing regression | Validation function + integration test with env override |
| R2 | Prompt compaction strips decision-relevant context | Lower plan/review quality | Keep immutable plan + latest review findings; human gate catches issues |
| R3 | Cache key collision (hash weakness) | Stale output reused | SHA-256 collision is negligible; git tree hash provides strong differentiation |
| R4 | Context7 MCP latency or failure blocks pipeline | Stuck pipeline | Timeout + graceful fallback (continue without Context7) |
| R5 | `.ai-models.env` committed with user-specific values | Config conflicts | Ship with sensible defaults; document override-via-env pattern |

## Open Questions
None blocking. All decisions are reversible via AD-7 rollback plan.

## Acceptance Criteria
- [ ] AC-1: `.ai-models.env` exists at repo root with all model config variables and safe defaults.
- [ ] AC-2: `task_flow.sh` loads `.ai-models.env` with `load_model_config()` function; env vars override file values.
- [ ] AC-3: No hardcoded model IDs remain in `task_flow.sh` logic (all reference config variables).
- [ ] AC-4: `CONTEXT7_ENABLED=0` in config; when set to `1`, plan/review phases use Context7 MCP; failure logs warning and continues.
- [ ] AC-5: `compact_task_context()` strips mutable sections; plan/review send compacted context.
- [ ] AC-6: `.task-cache/` directory used for plan/review caching; key = `sha256(phase + model + compact_content + git_tree_hash)`.
- [ ] AC-7: `NO_CACHE=1` bypasses cache; `make task-cache-clean` clears cache directory.
- [ ] AC-8: Existing guardrails preserved: branch safety, immutable plan guard, retry caps, staged review requirement.
- [ ] AC-9: `make task-prepare`, `task-plan`, `task-build`, `task-review`, `task-rework`, `task-ship`, `task-all` all work identically to before (backward compatible).
- [ ] AC-10: `ReadMe.md` updated with "How config works", "How cache works", "How to disable/tune" subsections.
- [ ] AC-11: `docs/workflows/ai-task-flow.md` updated with config loading, caching, compaction, and Context7 documentation.
- [ ] AC-12: `.task-cache/` added to `.gitignore`.

## File-by-File Change Plan

### New files
| File | Purpose |
|------|---------|
| `.ai-models.env` | Model routing config: `PLAN_MODEL`, `REVIEW_MODEL`, `REVIEW_ESCALATION_MODEL`, `CODEX_TIMEOUT_MINUTES`, `ENABLE_CAFFEINATE`, `COPILOT_TOOL_MODE`, `CONTEXT7_ENABLED`, `MAX_RETRIES`, `NO_CACHE` |

### Modified files
| File | Changes |
|------|---------|
| `scripts/task_flow.sh` | (1) Add `load_model_config()` — source `.ai-models.env`, validate, print routing table. (2) Add `compact_task_context()` — strip mutable sections from task file string. (3) Add `cache_key()` + `cache_get()` + `cache_put()` — SHA-256 based read-through cache. (4) Add `context7_available()` + conditional MCP flags in plan/review Copilot invocations. (5) Remove hardcoded defaults from lines 5-10, replace with `load_model_config()` call. (6) Wrap plan phase output with cache get/put. (7) Wrap review phase output with cache get/put. (8) Pass compacted context to plan/review model invocations. |
| `Makefile` | Add `task-cache-clean` target: `rm -rf .task-cache/` |
| `.gitignore` | Add `.task-cache/` entry |
| `ReadMe.md` | Add subsections under "AI Task Workflow": "Model Configuration", "Prompt Caching", "Context7 MCP (Optional)" |
| `docs/workflows/ai-task-flow.md` | Add sections: "Configuration", "Prompt Compaction", "Caching", "Context7 Integration" |

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Create `.ai-models.env` with all config variables and defaults
- [ ] Add `.task-cache/` to `.gitignore`
- [ ] Implement `load_model_config()` in `task_flow.sh`
- [ ] Remove hardcoded model defaults from top of `task_flow.sh`; call `load_model_config()`
- [ ] Implement `compact_task_context()` in `task_flow.sh`
- [ ] Implement `cache_key()`, `cache_get()`, `cache_put()` in `task_flow.sh`
- [ ] Implement `context7_available()` and conditional MCP flags in `task_flow.sh`
- [ ] Wire compaction into plan phase prompt construction
- [ ] Wire compaction into review phase prompt construction
- [ ] Wire cache get/put around plan phase model call
- [ ] Wire cache get/put around review phase model call
- [ ] Add `task-cache-clean` target to `Makefile`
- [ ] Update `ReadMe.md` with config/cache/Context7 documentation
- [ ] Update `docs/workflows/ai-task-flow.md` with config/cache/compaction/Context7 sections
- [ ] Run `make task-plan TASK=tasks/issue-107-pipeline-hardening.md` to verify plan phase works
- [ ] Run `make task-review TASK=tasks/issue-107-pipeline-hardening.md` to verify review phase works
- [ ] Verify `NO_CACHE=1` bypasses cache
- [ ] Verify env var override still takes precedence over `.ai-models.env`
- [ ] Verify existing guardrails (immutable plan guard, branch safety) are intact

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-107-pipeline-hardening.md
make task-build TASK=tasks/issue-107-pipeline-hardening.md
make task-review TASK=tasks/issue-107-pipeline-hardening.md
make task-rework TASK=tasks/issue-107-pipeline-hardening.md
make task-ship TASK=tasks/issue-107-pipeline-hardening.md
```
