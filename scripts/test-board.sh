#!/bin/bash
# Tests for scripts/board.py (#453) against a fake gh: one query + one mutation for many issues,
# the ID cache, back-off on a rate limit, nothing moved when an issue isn't on the board.
set -u
src=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
cleanup() { find "$tmp" -mindepth 1 -delete 2>/dev/null; rmdir "$tmp" 2>/dev/null; }
trap cleanup EXIT
pass=0; fail=0
ok() { echo "ok   $1"; pass=$((pass+1)); }
bad() { echo "FAIL $1" >&2; fail=$((fail+1)); }

# Fake gh: logs each call's query to $tmp/calls, answers from the query's shape. $tmp/ratelimit holds
# how many calls to refuse first with a secondary rate limit.
cat >"$tmp/gh" <<'GH'
#!/usr/bin/env python3
import json, os, re, sys
d = os.environ["FAKE_DIR"]
rl = os.path.join(d, "ratelimit")
if os.path.exists(rl) and int(open(rl).read() or 0) > 0:
    left = int(open(rl).read())
    open(rl, "w").write(str(left - 1))
    sys.stderr.write("gh: You have exceeded a secondary rate limit (HTTP 403)\n")
    sys.exit(1)
query = next(a[6:] for a in sys.argv if a.startswith("query="))
open(os.path.join(d, "calls"), "a").write(query.replace("\n", " ") + "\n")
if "projectV2(number" in query:
    print(json.dumps({"data": {"user": {"projectV2": {"id": "P", "fields": {"nodes": [
        {"id": "FS", "name": "Status", "options": [{"id": "o-ip", "name": "In progress"}, {"id": "o-fr", "name": "Fixed-To Review"}]},
        {"id": "FP", "name": "Priority", "options": [{"id": "o-p1", "name": "P1 High"}, {"id": "o-p3", "name": "P3 Low"}]},
        {}]}}}}}))
elif query.startswith("query{repository"):
    nodes = {}
    for n in re.findall(r"i(\d+):issue", query):
        mine = [{"id": "IT" + n, "project": {"id": "P"}}] if n != "999" else []
        nodes["i" + n] = {"id": "I" + n, "projectItems": {"nodes": mine + [{"id": "X", "project": {"id": "OTHER"}}]}}
    print(json.dumps({"data": {"repository": nodes}}))
elif query.startswith("mutation"):
    out = {a: {"item": {"id": "NEW" + a[1:]}} for a in re.findall(r"(a\d+):addProjectV2ItemById", query)}
    out.update({a: {"clientMutationId": None} for a in re.findall(r"(m\d+_\d+):update", query)})
    print(json.dumps({"data": out}))
else:
    sys.exit("unexpected query: " + query)
GH
chmod +x "$tmp/gh"
board() { FAKE_DIR=$tmp BOARD_GH=$tmp/gh BOARD_CACHE=$tmp/cache.json BOARD_BACKOFF=0 "$src/scripts/board.sh" "$@"; }
calls() { if [ -f "$tmp/calls" ]; then wc -l <"$tmp/calls" | tr -d ' '; else echo 0; fi; }
mutations() { grep -c '^mutation' "$tmp/calls" 2>/dev/null; }

out=$(board move 359 361 362 "Fixed-To Review" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(calls)" = 3 ] && [ "$(mutations)" = 1 ] &&
  [ "$(grep -o 'm[0-9]*_0:update' "$tmp/calls" | wc -l | tr -d ' ')" = 3 ] &&
  grep -q 'itemId:"IT361",fieldId:"FS",value:{singleSelectOptionId:"o-fr"}' "$tmp/calls" &&
  ok "move 3 issues: IDs + one lookup + one mutation" || bad "move: rc=$rc calls=$(calls) $out"

: >"$tmp/calls"
board move 363 "In prog" >/dev/null 2>&1
[ "$(calls)" = 2 ] && ! grep -q 'projectV2(number' "$tmp/calls" && grep -q 'o-ip' "$tmp/calls" &&
  ok "second run uses the cached IDs; option matched by prefix" || bad "cache: calls=$(calls)"

: >"$tmp/calls"
out=$(board move 363 Done 2>&1); rc=$?
[ "$rc" != 0 ] && printf '%s' "$out" | grep -q "Done" && [ "$(mutations)" = 0 ] &&
  ok "unknown status: error, nothing changed" || bad "bad status: rc=$rc $out"

: >"$tmp/calls"
out=$(board move 363 999 "Fixed-To Review" 2>&1); rc=$?
[ "$rc" != 0 ] && printf '%s' "$out" | grep -q "not on the board: #999" && [ "$(mutations)" = 0 ] &&
  ok "an issue not on the board: nothing moved" || bad "not on board: rc=$rc $out"

: >"$tmp/calls"
out=$(board add 999 363 "In progress" P1 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q 'a999:addProjectV2ItemById' "$tmp/calls" && ! grep -q 'a363:add' "$tmp/calls" &&
  grep -q 'itemId:"NEW999",fieldId:"FP",value:{singleSelectOptionId:"o-p1"}' "$tmp/calls" &&
  grep -q 'itemId:"IT363",fieldId:"FS"' "$tmp/calls" && [ "$(calls)" = 3 ] &&
  ok "add: only the missing one is added; fields set in one mutation" || bad "add: rc=$rc calls=$(calls) $out"

: >"$tmp/calls"; echo 2 >"$tmp/ratelimit"
out=$(board move 359 "In progress" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(printf '%s' "$out" | grep -c 'rate limit; retrying')" = 2 ] &&
  ok "rate limit: retried with back-off, then succeeded" || bad "rate limit: rc=$rc $out"

echo 9 >"$tmp/ratelimit"
out=$(board move 359 "In progress" 2>&1); rc=$?
[ "$rc" = 1 ] && printf '%s' "$out" | grep -q "secondary rate limit" &&
  ok "rate limit that doesn't clear: fails after the retries" || bad "rate limit forever: rc=$rc $out"
echo 0 >"$tmp/ratelimit"

out=$(board 2>&1); rc=$?
[ "$rc" = 2 ] && printf '%s' "$out" | grep -q "board.sh move <issue#>" && ok "usage" || bad "usage: rc=$rc"

echo "board: $pass passed, $fail failed"
[ "$fail" = 0 ]
