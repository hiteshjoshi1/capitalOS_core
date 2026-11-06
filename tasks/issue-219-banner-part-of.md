# Issue 219: Test banner shows "Part of #N" issues instead of the PR number

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/219

## Objective
- The red TEST banner (#200) names the issue a batch PR works on even when the PR closes none of them, e.g. a Dependabot batch for the long-running #49 shows `#49`, not its own PR number.
- The test PR (`make test-instance-pr`) names the same issues: `Closes` only for what the batch closes, `Part of` for the rest.

## Architecture Decisions
- One resolver, `pr_issue_refs` in `scripts/test-instance.sh`, used by both the banner (`banner_refs`) and the test PR body (`batch_issues`), so the two can't drift. Per PR, in order:
  1. `close`: GitHub's `closingIssuesReferences`, plus `Closes` / `Fixes` / `Resolves #N` (any GitHub keyword form) in the body.
  2. `part` (only when it closes none): `Part of #N` / `Refs #N` in the body, else the `(#N)` that ends the title.
  3. `pr`: the PR number itself.
- The test PR body keeps `Closes #N` for `close` issues only, so merging it never closes a long-running issue like #49; `part` issues get a `Part of #N` line (not a closing keyword).
- One `gh pr view` per PR (closing refs, title, body). A PR gh can't read shows as itself on the banner; `make test-instance-pr` stops before pushing, naming it, rather than open a PR with a missing `Closes`.
- The script can now be sourced (functions only) for its test, like `db-backup.sh`.

## Acceptance Criteria
- [x] A batch with a "Part of #49" PR shows `#49` on the banner, linked to the issue (the link is #200's `/issues/N`).
- [x] The known failure: #215 "Dependabot batch 7 … (#49)" (body says "for #49", no keyword) resolves to `#49`.
- [x] The test PR body: `Closes` for what the batch closes, `Part of #49` for the Dependabot batch, never `Closes #49`.

## How To Test
- `scripts/test-test-instance.sh` (also run by `make lint`): 15 checks with a stub `gh`, no network.
- Against GitHub, read-only (the #218 batch): source the script, set `STATE` to a temp file with `merged= 216 214 217 215`, run `banner_refs` → `207 211 158 49` (was `207 211 158 215`), and `batch_issues` → `Closes #158`, `Closes #207`, `Closes #211`, `Part of #49`.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results
- `scripts/test-test-instance.sh`: 15 passed, 0 failed. With the title fallback removed, 2 fail (the #215 case and the batch banner), so the test catches the reported bug.
- Read-only run against the real #218 batch PRs: as above.
- `make lint`: see the PR.
