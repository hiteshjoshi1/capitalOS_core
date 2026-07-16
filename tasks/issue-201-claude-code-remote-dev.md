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
- [ ] Confirm current `claude.ai/code` web-sandbox capabilities/limits via `claude-code-guide` agent (do this before writing the doc, not after)
- [ ] Write the remote-dev doc covering both paths
- [ ] Cross-reference `CLAUDE.md`
- [ ] Manually verify both paths per "How To Test"

## Execution Journal (Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
- Provider/Model: `<provider>/<model>`
- Last Updated: `2026-07-16`

## Deterministic Gate Results (Mutable)
_Append command-level evidence here._
- `web path manual test`: `<pass|fail|skip>` — `<notes>`
- `ssh/tmux path manual test`: `<pass|fail|skip>` — `<notes>`

## Human Action Summary (Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - Where should the doc actually live — new `docs/remote-dev.md`, or folded into `ReadMe.md`? Pick at execution time based on which reads better in context; not pre-decided here since it's a cosmetic call, not an architecture one.
