# Issue 202: Claude Code RAG/Research Tooling (Phase 3, trimmed)

## Objective
- Give Claude Code a native, read-only way to inspect the RAG/research corpus (authors, sources, documents, ingestion jobs) instead of hand-writing `docker exec psql` one-liners or `docker compose exec api python -c "..."` scripts every time — both of which are either slow to construct correctly or (in the python-eval case) deliberately kept behind a permission prompt because they're equivalent to arbitrary code execution against a container with DB write access.
- Capture the author-ingestion workflow (`config/rag_authors.yaml` → `POST /rag/authors/sync-config` → URL ingestion → selective-ingestion/fanout options) as a skill, since it has enough moving parts (progressive disclosure, selective options, fanout configs) to be worth documenting once rather than rediscovering per session.

This is a **trimmed Phase 3** of the Claude Code DX upgrade (see `tasks/issue-199-claude-code-dx-upgrade.md` for Phase 1, which shipped `CLAUDE.md`, the allowlist + `PreToolUse` hook, and the `run`/`verify` project skills). The original Phase 1 backlog listed four items for Phase 3; this issue deliberately covers only two of them — see "Explicitly out of scope" below for why the other two (three custom agent defs) are deferred, not forgotten.

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
- [ ] Pick and configure a maintained read-only Postgres MCP server in `.mcp.json`
- [ ] Verify one real read-only query works end to end via the MCP tool
- [ ] Write `.claude/skills/corpus-inspect/SKILL.md`
- [ ] Write `.claude/skills/ingestion/SKILL.md`
- [ ] Update `CLAUDE.md`'s RAG section to cross-reference the new skills if it reads better that way

## Execution Journal (Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
- Provider/Model: `<provider>/<model>`
- Last Updated: `2026-07-16`

## Deterministic Gate Results (Mutable)
_Append command-level evidence here._
- `mcp query smoke test`: `<pass|fail|skip>` — `<notes>`

## Human Action Summary (Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - Which specific Postgres MCP server package to use — check what's current/maintained at execution time rather than trusting a name written down today.
  - Does the chosen MCP server need actual DB-level read-only credentials, or is "the server only ever issues SELECT" sufficient given this is a solo-dev local Postgres instance? Lean toward the simpler option unless there's a concrete reason not to.
