# Issue 202: Claude Code RAG/Research Tooling (Phase 3, trimmed)

## Objective
- Give Claude Code a native, read-only way to inspect the RAG/research corpus (authors, sources, documents, ingestion jobs) instead of hand-writing `docker exec psql` one-liners or `docker compose exec api python -c "..."` scripts every time — both of which are either slow to construct correctly or (in the python-eval case) deliberately kept behind a permission prompt because they're equivalent to arbitrary code execution against a container with DB write access.
- Capture the author-ingestion workflow (`config/rag_authors.yaml` → `POST /rag/authors/sync-config` → URL ingestion → selective-ingestion/fanout options) as a skill, since it has enough moving parts (progressive disclosure, selective options, fanout configs) to be worth documenting once rather than rediscovering per session.

This is a **trimmed Phase 3** of the Claude Code DX upgrade (see `tasks/issue-199-claude-code-dx-upgrade.md` for Phase 1, which shipped `CLAUDE.md`, the allowlist + `PreToolUse` hook, and the `run`/`verify` project skills). The original Phase 1 backlog listed several items for Phase 3; this issue deliberately covers only two of them (Postgres MCP access + the `corpus-inspect` skill it enables, and the `ingestion` skill) — see "Explicitly out of scope" below for why the other three (custom agent defs: `company-researcher`, `rag-evaluator`, `contract-guardian`) are deferred, not forgotten.

## Current State
- No `.mcp.json` exists in this repo — no MCP servers configured at all.
- No `.claude/skills/corpus-inspect/` or `.claude/skills/ingestion/` exist.
- `.claude/skills/verify/SKILL.md` (Phase 1) already documents the `make rag-eval*` commands — that item from the original Phase 1 backlog is already covered and is **not** part of this issue.
- Evidence this is real, not speculative: during the Author Library/Ingestion redesign work (see `tasks/issue-19x-*` research-section work) and the Phase 1 DX audit, the same class of ad hoc query got hand-written multiple times: "how many documents does author X have," "which `user_id` owns these `rag_sources` rows," "did the `photo_url` config change actually take effect." Each of those was a fresh `docker exec`/`python -c` invocation, not a documented, reusable one.

## Architecture Decisions
- **Postgres MCP**: use an existing, maintained read-only Postgres MCP server (e.g. the official `@modelcontextprotocol/server-postgres` or equivalent — check what's current/maintained at execution time, don't assume a specific package name is still the right one) rather than writing a custom one. Configure it in `.mcp.json` pointed at the same Postgres instance `docker-compose.yml` already defines (`capitalos-postgres`, database `capitalos`), with **read-only** credentials if the server supports scoping that at the connection level — if it only supports read-only at the "the server itself only issues SELECTs" level (most MCP Postgres servers work this way, not via a separately-scoped DB role), that's acceptable; don't create a whole new Postgres role/permission scheme just for this unless the chosen server actually needs one.
- **`corpus-inspect` skill**: not a wrapper around the MCP tool calls themselves (the MCP tool descriptions do that) — instead, document the *questions worth asking* and the schema knowledge needed to ask them well: which tables matter (`rag_authors`, `rag_sources`, `rag_documents`, `rag_ingestion_jobs`, `realtime_events`), what `user_id` ownership means on `rag_sources`/`rag_ingestion_jobs` (see the ownership-unification work from Phase 1's session — `migrations/066_unify_rag_source_ownership.sql` — for why this matters and what "current" looks like), and a handful of ready-made read-only queries (author doc counts by owner, stuck/queued ingestion jobs, recent ingestion activity).
- **`ingestion` skill**: document the full author-ingestion flow end to end: `config/rag_authors.yaml` fields (id, domains, expertise_tags, weight, role_type, `photo_url`) → bind-mount live-reload (no rebuild needed, per `CLAUDE.md`) → `POST /rag/authors/sync-config` when DB-backed fields change → `POST /rag/authors/{id}/ingest-urls` for source ingestion → selective-ingestion options (start/stop heading, include/exclude sections) → fanout config (logical-document splitting) and its preview endpoint. Reference the real request/response shapes from `api/app/routers/rag.py` rather than re-describing them loosely.
- Both skills should explicitly note: anything that **mutates** the corpus (registering sources, running ingestion, deleting/reassigning ownership) still goes through the app's own endpoints or a tracked `migrations/NNN_*.sql` file — never through the MCP connection or a direct psql write, regardless of how convenient that would be. The MCP server itself being read-only is the enforcement mechanism; state that explicitly so a future session doesn't quietly try to configure a writable one "for convenience."

## Explicitly out of scope (deferred, not rejected)
- **`company-researcher` agent** — the Companies screen is still a "coming soon" placeholder with no real dossier data model. Revisit once that feature has actual structure to research against; defining the agent now would be guessing at its own interface.
- **`rag-evaluator` agent** — no demonstrated recurring need beyond what the `verify` skill's `make rag-eval*` commands already provide. Revisit if eval-report interpretation becomes a repeated, non-trivial task.
- **`contract-guardian` agent** — the OpenAPI/TS-parity rule it would enforce already exists in `AGENTS.md`. Revisit whether this needs a dedicated custom agent vs. a `PostToolUse` hook vs. relying on the existing `code-review` skill, once there's a concrete instance of the rule actually being violated in review.

## Acceptance Criteria
- [ ] `.mcp.json` configures a read-only Postgres MCP server pointed at the `capitalos-postgres` container/database.
- [ ] A representative read-only query (e.g. "list authors with document counts") works via the MCP tool in a live session, without falling back to `docker exec psql`.
- [ ] `.claude/skills/corpus-inspect/SKILL.md` exists, covering the schema/ownership knowledge and at least 3 ready-made example queries.
- [ ] `.claude/skills/ingestion/SKILL.md` exists, covering the full config → sync → ingest-urls → selective/fanout flow with real endpoint references.
- [ ] Both new skills explicitly state the read-only/mutate-via-app-endpoints boundary.
- [ ] `CLAUDE.md`'s existing "RAG / research corpus" section is updated to point at the new skills instead of (or in addition to) its current brief inline summary, if that reads better once the skills exist.

## How To Test
- Ask Claude Code (fresh session) "how many documents does each author have, and which are missing a canonical `user_id`" — confirm it reaches for the MCP tool rather than constructing a `docker exec` command from scratch.
- Ask Claude Code to walk through adding a new author via `config/rag_authors.yaml` and ingesting one URL for them — confirm it follows the `ingestion` skill's flow (sync-config, then ingest-urls) rather than re-deriving the endpoint sequence.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Pick and configure a maintained read-only Postgres MCP server in `.mcp.json`
- [x] Verify one real read-only query works end to end via the MCP tool
- [x] Write `.claude/skills/corpus-inspect/SKILL.md`
- [x] Write `.claude/skills/ingestion/SKILL.md`
- [x] Update `CLAUDE.md`'s RAG section to cross-reference the new skills

## Execution Journal (Codex Mutable)
- Current Stage: `shipped, pending PR`
- Workflow Status: `waiting_for_human` (manual verification per "How To Test" — see below)
- Provider/Model: `claude-code/sonnet-5`
- Last Updated: `2026-07-25`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `mcp server selection`: `pass` — researched at execution time per the plan's explicit instruction not to assume a package name. The official `@modelcontextprotocol/server-postgres` is archived/deprecated and has a disclosed SQL-injection advisory that can bypass its read-only mode — explicitly avoided. Chose `crystaldba/postgres-mcp` ("Postgres MCP Pro"): actively maintained, supports `--access-mode=restricted` which validates/rejects non-SELECT statements before they reach the database (stronger than the plan's stated minimum bar of "the server only issues SELECTs").
- `mcp query smoke test`: `pass` — ran the actual JSON-RPC stdio protocol by hand (`initialize` → `tools/list` → `tools/call execute_sql`) against the exact `docker run` command configured in `.mcp.json`. Confirmed: (1) server starts in RESTRICTED mode and connects to the real `capitalos-postgres` DB; (2) `tools/list` returns `execute_sql` plus schema-inspection tools; (3) a real SELECT (`rag_authors` LEFT JOIN `rag_documents` doc-count-by-author) returned accurate live data matching known state (Howard Marks 164, Michael Mauboussin 2, etc.); (4) a `DELETE FROM rag_authors` was rejected with a validation error, never executed — read-only enforcement confirmed at the query-validation level, not just convention.
- `corpus-inspect example queries`: `pass` — all 5 ready-made queries in the skill run correctly against the live DB via `docker exec psql` (ownership-drift query, stuck-jobs query, missing-stored-file query, realtime-events query, config-sync-check query); output cross-checked against known corpus state.
- `ingestion skill endpoint accuracy`: `pass` — every endpoint path/method referenced in the skill (`sync-config`, `authors` POST, `ingest-urls`, `fanout/preview`, `ingest/pdf/upload`, `sources/{id}/file`, `ingest/retry/{id}`, `ingest/activity`) cross-checked against the live `@router.*` decorator list in `api/app/routers/rag.py`; one inaccuracy found and fixed (`ingest/activity`, not `ingestion-activity/{author_id}`) before shipping.
- `.mcp.json` / `.claude/settings.json` JSON syntax: `pass` — `python3 -m json.load` on both.
- skill frontmatter YAML syntax: `pass` — both `SKILL.md` files parse as valid YAML frontmatter.
- `backend full suite`: `pass` — `docker compose run --rm api pytest -q` — exit 0, no failures (no backend code was touched by this issue; run as a safety net).
- `frontend full suite`: `pass` — `npx tsc --noEmit` clean, `npx vitest run` 292/292 (no frontend code was touched by this issue; run as a safety net).
- `api health check`: `pass` — `curl localhost:8000/health` → 200.
- `web path manual test` / `ssh/tmux path manual test`: not applicable to this issue (belongs to issue-201).

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `.claude/settings.json` — added `git checkout`/`git pull`/`git fetch`/`git branch`, `docker run`/`docker pull`/`docker network inspect`/`docker images`, and `kill` to the permission allowlist. Needed mid-task to actually create this branch and run the live MCP smoke tests without per-command prompts; same rationale/pattern as the Phase 1 allowlist work.
- Fixed an internal inconsistency in this task doc's own "Objective" paragraph (said "covers only two... other two (three custom agent defs)" — contradicted itself) before implementing, per explicit instruction.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `Not applicable — shipped.`
- Attempted mitigations:
  - `None required.`
- Suggested human action: `See Human Action Summary below.`

## Human Action Summary (Codex Mutable)
- Next expected action: Run the two conversational "How To Test" checks from a fresh Claude Code session (ask the corpus-count question, ask to walk through adding an author + ingesting a URL) to confirm a *fresh* session actually reaches for the MCP tool / follows the skill rather than reverting to old habits — that's a behavioral check on future sessions, not something this session can self-verify. See the chat response for the exact prompts to use.
- Open questions:
  - None outstanding on the technical implementation. One soft dependency: `.mcp.json`'s `--network capitalos_default` name is derived from the repo directory name by Docker Compose's default naming — if the repo is ever renamed or `COMPOSE_PROJECT_NAME` is set, this needs updating.
- If PR raised but intent partial:
  - unmet criteria: None — all Acceptance Criteria items are met. Only the two manual "How To Test" conversational checks remain, same category of "requires a human/fresh-session in the loop" as issue-201's device tests.
  - follow-up issue: Not needed unless the manual checks surface a fresh session not using the tooling as intended — fix the skill's discoverability (description wording) in place if so, rather than filing a new issue.

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
