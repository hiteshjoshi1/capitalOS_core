# Issue 255: Safety hook: a commit with a message file followed by a plain push is refused as a force push

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/255

## Objective
- `git commit -F msg.txt && git push` (and any line where only another command has a `-F`/`-f`,
  or where a quoted issue/PR body mentions a forced push) is no longer refused by the PreToolUse guard.
- Every form of forced push is still refused, including forms the old check missed
  (`git -C dir push -f`, `-fu`, `origin +main`, `--force-if-includes`).
- A test script with must-block and must-pass cases runs in `make lint` (so `make verify` and CI).

## Architecture Decisions
- D-70 (docs/decisions.md). Rule 2 of `.claude/hooks/pretooluse-guard.sh` now asks
  `.claude/hooks/pretooluse-force-push.awk`, which splits the command into simple commands the way
  the shell does (separators, quotes, backslashes, heredocs, `$(...)`, backquotes, `bash -c`, `eval`,
  `ssh`, a shell reading its stdin) and judges each `git push` by its own arguments.
- awk, not bash: bash 3.2 (macOS `/bin/bash`, which the hook runs under) re-measures the string on
  every `${s:i:1}`, so a bash parser took 2-4 s on a 50-70 KB command. The awk reader takes about
  0.3 s for the whole hook at 70 KB. A command with no `push` in it skips the reader.
- If awk fails (exit 2), the old whole-line check decides: the hook fails closed.
- Rules 1, 3 and 4 are unchanged (they now have regression cases too).

## Acceptance Criteria
- [x] `git commit -F msg.txt && git push` passes.
- [x] `-f`, `-fu`/`-uf`, `--force`, `--force-with-lease[=...]`, `--force-if-includes`, `--forc`,
      `--mirror`, `+refspec` are refused, also after `git -C dir`, `&&`, `;`, `||`, `|`, newlines,
      prefixes (`env`, `timeout`, `xargs`, `if`), in `bash -c`, `eval`, `$(...)`, backquotes, `ssh`,
      `bash <<EOF`, `echo ... | bash`.
- [x] An issue/PR body in a quoted argument or quoted heredoc that mentions a forced push passes.
- [x] `scripts/test-pretooluse-guard.sh` runs in `make lint`.

## How To Test
- `scripts/test-pretooluse-guard.sh`: every case in `scripts/test-pretooluse-guard.cases` passes,
  plus a 30 KB PR body within time and the no-reader fallback.
- Put new cases in the cases file (Write tool), not on a Bash command line: the live hook in the
  main checkout reads every command and still has the old rule until this is deployed.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `review`
- Workflow Status: `shipped`
- Provider/Model: `anthropic/claude-opus-5-5`
- Last Updated: `2026-11-06`

Known limits (documented in the awk header and D-70): a force hidden in a variable
(`git push $FLAGS`), a git alias, a function or script defined elsewhere, and remote config
(`remote.<name>.mirror`, `+` in a configured refspec) are not seen; the permission prompt stays
the guard there. An unquoted heredoc's backquotes are read as commands (the shell does run them),
so a markdown body in `<<EOF` (not `<<'EOF'`) that shows a forced push in backquotes is refused.

## Deterministic Gate Results (Codex Mutable)
- `scripts/test-pretooluse-guard.sh`: pass, 94 cases + 4 extra checks. The old hook fails 24 of them.
- The reader alone, on the 82 rule-2 cases: macOS awk 20200816 and mawk 1.3.4 (Debian image): all pass.
- Timing (whole hook, macOS /bin/bash 3.2): 50 KB / 3000-word command with a push 0.30 s; 70 KB
  double-quoted body with a push 0.30 s; without `push` 0.05-0.15 s.
- `make verify`: see the PR.

## Extra Files Changed (Codex Mutable)
- `.claude/skills/verify/SKILL.md` — reason: how to verify a hook change.

## Permanently Failed / Gave Up (Codex Mutable)
- n/a

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR; after merge, `make deploy` (the hook is read from the
  main checkout, so it applies once main has it).
- Open questions: none.

## Automation Log (Mutable)

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
