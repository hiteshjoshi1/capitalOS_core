#!/usr/bin/env bash
set -euo pipefail

TASK_FILE="$1"

if [[ -z "$TASK_FILE" ]]; then
  echo "Usage: scripts/run_task.sh tasks/issue-123-title.md"
  exit 1
fi

BASENAME=$(basename "$TASK_FILE")
ISSUE_ID=$(echo "$BASENAME" | sed -E 's/^issue-([0-9]+).*/\1/')
SLUG=$(echo "$BASENAME" | sed -E "s/^issue-${ISSUE_ID}-//; s/\.md$//")

BRANCH="codex/issue-${ISSUE_ID}-${SLUG}"

echo "==> Preparing branch $BRANCH"

git checkout main
git pull --rebase
git checkout -b "$BRANCH"

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
   If failures occur, fix them (max 2 attempts per failing command).
   If still failing, document blockers in $PLAN and stop."

echo "==> Attempting E2E..."

codex exec --full-auto --sandbox workspace-write \
  "If Playwright exists, add minimal e2e tests for happy path and run make e2e.
   Max 2 fix attempts.
   If e2e missing, update $PLAN recommending scaffold."

echo "==> Committing"

git add -A
git commit -m "Codex: implement issue #${ISSUE_ID}" || echo "No changes"

git push --set-upstream origin "$BRANCH"

echo "==> Done. Create PR manually or run:"
echo "gh pr create --base main --head $BRANCH"