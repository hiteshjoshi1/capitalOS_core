#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: scripts/run_task.sh tasks/issue-123-title.md"
}

run_with_timeout() {
  local duration="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$duration" "$@"
    return
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$duration" "$@"
    return
  fi
  echo "WARN: timeout command not found; running without timeout"
  "$@"
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

TASK_FILE="$1"
if [[ ! -f "$TASK_FILE" ]]; then
  echo "Task file not found: $TASK_FILE"
  exit 1
fi

BASENAME=$(basename "$TASK_FILE")
ISSUE_ID=$(echo "$BASENAME" | sed -E 's/^issue-([0-9]+).*/\1/')
SLUG=$(echo "$BASENAME" | sed -E "s/^issue-${ISSUE_ID}-//; s/\.md$//")
if [[ ! "$BASENAME" =~ ^issue-[0-9]+-.*\.md$ ]]; then
  echo "Task filename must match issue-<id>-<slug>.md"
  usage
  exit 1
fi

BRANCH="codex/issue-${ISSUE_ID}-${SLUG}"

echo "==> Preparing branch $BRANCH"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is dirty. Commit/stash local changes before running autonomous flow."
  exit 1
fi

git checkout main
git pull --rebase
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
fi

mkdir -p docs/plans
PLAN="docs/plans/${ISSUE_ID}.md"
cp "$TASK_FILE" "$PLAN"

echo "==> Running Codex planner..."

codex exec --full-auto --sandbox workspace-write \
  "Read $PLAN. Expand it into a full plan with:
   - Architecture decisions
   - DB changes
   - API routes
   - Frontend components
   - Test plan
   - Open questions.
   If critical ambiguity exists, document it and STOP."

echo "==> Running Codex implementation..."

codex exec --full-auto --sandbox workspace-write \
  "Implement per $PLAN.
   Add backend and frontend tests.
   Run: make lint && make typecheck && make test-backend && make test-frontend.
   If task touches market data, prices, FX, valuation, or net worth:
   - Capture BEFORE snapshot queries and write them to $PLAN:
     1) dashboard summary total for target month
     2) sample holdings values for affected symbols
     3) currency consistency check:
        SELECT count(*) FROM prices p JOIN assets a ON a.id=p.asset_id
        WHERE p.trade_date IS NOT NULL AND p.source LIKE '%_market'
          AND upper(coalesce(p.currency,'')) <> upper(coalesce(a.quote_currency,''));
   - After implementation, run same checks and compare.
   - Reject completion if currency consistency count != 0.
   - If provider returns missing/invalid price, do not update existing stored price rows.
   - Validate provider keys exist before live refresh attempts and log any missing keys in $PLAN.
   If failures occur, fix them (max 2 attempts per failing command).
   If still failing, document blockers in $PLAN and stop."

echo "==> Attempting E2E..."

run_with_timeout 60m codex exec --full-auto --sandbox workspace-write \
  "If Playwright exists, add minimal e2e tests for happy path and run make e2e.
   Max 2 fix attempts.
   If e2e missing, update $PLAN recommending scaffold."

echo "==> Committing"

git add -A
git commit -m "Codex: implement issue #${ISSUE_ID}" || echo "No changes"

git push --set-upstream origin "$BRANCH"

echo "==> Done. Create PR manually or run:"
echo "gh pr create --base main --head $BRANCH"
