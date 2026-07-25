# Issue 201: Claude Code Remote Dev (Phase 4)

## Objective
- Let the user drive Claude Code on CapitalOS from a phone, without needing remote desktop, mirroring how their friends already work (laptop stays home, commands come from a phone).
- Document two complementary paths rather than picking one: a cloud-sandbox path for lightweight/ambiguous work, and a "reach my real machine" path for anything that needs the live Docker/Postgres stack, local ports, or data already seeded on that machine.

This is **Phase 4** of the Claude Code DX upgrade (see `tasks/issue-199-claude-code-dx-upgrade.md` for Phase 1, which already shipped). Decisions below were locked during that planning pass via user Q&A ("Both web + Tailscale/tmux").

## Current State
- No remote-dev setup exists today beyond whatever the user already does manually.
- CapitalOS is local-first by design (`AGENTS.md`: "Local-first AI-native personal finance + investing system") — the live stack (Postgres+pgvector, api, seeded demo/dev data) only exists on the user's home machine via `docker-compose.yml`. There is no hosted/staging copy.
- `claude.ai/code` (the web product) runs Claude Code sessions in a managed cloud sandbox — it does not have network access to the user's home machine or its Docker containers unless something bridges them.
- The user's friends already work this way today (phone-driven Claude Code sessions against a laptop left running at home) — so a working pattern demonstrably exists; this issue is about documenting/hardening it for this repo specifically, not inventing it from scratch.

## Architecture Decisions
- **Decision (locked)**: support and document **both** paths, don't pick one:
  1. **`claude.ai/code` (web)** — for driving Claude Code from a phone browser when the task doesn't need the live local stack (code review, planning, docs, non-DB-dependent edits). Lowest friction, no setup on the user's end beyond logging in.
  2. **Tailscale + SSH + tmux to the home machine** — for anything that needs the real Postgres data, the running docker containers, or local ports (5173/8000). Claude Code is a TUI, so it runs natively over SSH; tmux keeps the session alive across phone app backgrounding/network drops, and lets the user reattach from a laptop later if they want to look at the same session.
- **Explicitly not doing**: remote desktop / VNC / screen-sharing of any kind. Unnecessary — Claude Code has no GUI dependency here, and RDP is heavier, less secure by default, and doesn't survive mobile network drops as gracefully as SSH+tmux.
- **Step 0 before writing the doc**: confirm current `claude.ai/code` web-sandbox networking limits and capabilities with the `claude-code-guide` agent — the plan's assumptions about what the web sandbox can/can't reach need to be checked against current product behavior before being written down as fact, since this changes over time.

## Acceptance Criteria
- [ ] A short doc (e.g. `docs/remote-dev.md`, or a section appended to `ReadMe.md` — pick whichever fits the repo's existing doc layout better) exists covering both paths below.
- [ ] **Web path** documented: how to open `claude.ai/code` against this repo, what it can and cannot do (confirmed via `claude-code-guide`, not assumed), and when to prefer it (no live-DB dependency).
- [ ] **Tailscale/SSH/tmux path** documented, concretely for this repo:
  - Tailscale install + auth on the home machine and the phone (link to Tailscale's own docs rather than re-authoring their onboarding).
  - SSH client recommendation for phone (e.g. Termius, Blink) — pick one, don't just list options, since the user asked for a working setup, not a survey.
  - Exact tmux invocation to start/reattach a durable session (`tmux new -s capitalos` / `tmux attach -t capitalos`), and why tmux specifically solves the "phone app backgrounds, session must survive" problem.
  - Reminder that `make up` + the demo login (`demo`/`Test@1234`, see `CLAUDE.md`) still apply once connected — this path doesn't change anything about how CapitalOS itself runs, only how the user reaches the terminal running it.
- [ ] Doc explicitly states the decision **not** to use remote desktop and why (one line — avoid re-litigating in the doc itself).
- [ ] Both paths cross-reference `CLAUDE.md` for the actual run/verify commands rather than duplicating them.

## How To Test
- Follow the web-path instructions from a phone browser against this repo; confirm a trivial read-only task (e.g. "what does `AGENTS.md` say about snapshot day") completes without needing local network access.
- Follow the Tailscale/SSH/tmux instructions end-to-end from a phone: connect, attach tmux, run `make up` + `curl localhost:8000/health`, confirm the response, then background the phone app and confirm the session is still alive on reattach.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Confirm current `claude.ai/code` web-sandbox capabilities/limits via `claude-code-guide` agent (do this before writing the doc, not after)
- [x] Write the remote-dev doc covering both paths
- [x] Cross-reference `CLAUDE.md`
- [ ] Manually verify both paths per "How To Test" — requires a physical phone; not something Claude Code can execute itself. Left for the user (see Human Action Summary).

## Execution Journal (Codex Mutable)
- Current Stage: `doc written, cross-referenced, awaiting manual device verification`
- Workflow Status: `waiting_for_human`
- Provider/Model: `claude-code/sonnet-5`
- Last Updated: `2026-07-23`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `claude-code-guide capability check`: `pass` — confirmed sandbox isolation (no home-network path), GitHub-based clone/push, per-session throwaway Postgres/Docker, restricted-by-default outbound access; doc written to match, not assumed.
- `web path manual test`: `skip` — requires an actual phone browser session against `claude.ai/code`; not executable from this environment.
- `ssh/tmux path manual test`: `skip` — requires an actual phone, Tailscale account, and SSH client; not executable from this environment.

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `CLAUDE.md` — added a one-line "Remote dev" pointer section so the doc is discoverable from the operational quickstart, not just from `ReadMe.md`. In scope per the plan's "cross-reference CLAUDE.md" acceptance criterion.
- `ReadMe.md` — added one link line next to the existing `ai-task-flow.md` reference, same doc-discoverability rationale.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `Not applicable — doc shipped; only the two manual device tests are outstanding.`
- Attempted mitigations:
  - `None required.`
- Suggested human action: `See Human Action Summary below.`

## Human Action Summary (Codex Mutable)
- Next expected action: Actually follow both paths from a phone per "How To Test" and confirm they work as documented (open `claude.ai/code` from a phone browser for a trivial read-only task; separately set up Tailscale + Termius + tmux and confirm `make up` + `curl localhost:8000/health` survives backgrounding the phone app).
- Open questions:
  - None outstanding — doc location (`docs/workflows/remote-dev.md`, alongside the existing `ai-task-flow.md`) was decided at execution time per the plan's explicit "pick whichever fits" latitude.
- If PR raised but intent partial:
  - unmet criteria: The two manual "How To Test" device walkthroughs are unverified (see above) — everything else in Acceptance Criteria is complete.
  - follow-up issue: Not needed unless manual verification surfaces an inaccuracy in the doc (e.g. product behavior differs from what `claude-code-guide` reported); fix in place if so.

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
