# Issue 43: Process rules: sprint approval, status flow, merge on Hitesh's word, decision log, self-review

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/43

## Objective
- Write down how work is approved, merged and reviewed, so every implementer (Claude, Codex,
  people) follows the same rules. Taken from InvestOS's AGENTS.md and this repo's own lessons.

## Architecture Decisions
- Rules live in **AGENTS.md § Process Rules**, which binds every implementer. CLAUDE.md only
  points to it (InvestOS's pattern: "a standing rule ... goes into AGENTS.md in the same change
  that first applies it").
- The self-review checklist names the concrete failures from this repo: the `db-backup`
  regression (#33 → fixed in #38) and the masked failure (`cmd | tail`, #38), so the rule says
  what to look for rather than "be careful".
- The supply-chain bullets codify what was already practised in #5–#40 (digest pins, the
  two-week release age, naming a new dependency first). They're recorded as D-1 and D-9.
- `docs/decisions.md` is seeded with D-1–D-12 from #5–#51, each with the rejected alternative and why.

## Acceptance Criteria
- [x] AGENTS.md has the sprint, merge, status, decision-log, self-review and reporting rules; CLAUDE.md points to them.
- [x] `docs/decisions.md` exists with 12 real decisions, each with its rejected alternative and PR.

## How To Test
- Read AGENTS.md § Process Rules and docs/decisions.md.

<!-- IMMUTABLE_PLAN_END -->
