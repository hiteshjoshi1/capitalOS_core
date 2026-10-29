#!/bin/bash
# The CapitalOS backlog board (GitHub Project #2, owner hiteshjoshi1) from the terminal (#42).
#   board.sh list [STATUS]                       items, optionally only one Status
#   board.sh add <issue#> [STATUS] [P] [SIZE] [KIND]
#                                                put an issue on the board, e.g.
#                                                board.sh add 50 "Next up" P2 S Ops
#   board.sh move <issue#> <STATUS>              e.g. board.sh move 50 "In progress"
# STATUS: "Next up" | "In progress" | "Fixed-To Review" | "Waiting on Hitesh" | Backlog | Done
# P: P0..P3   SIZE: S | M | L   KIND: Ops | Process | Feature | Bug | Security | "Tech debt"
# Option values match by prefix, so P1 matches "P1 High" and S matches "S (under a day)".
set -euo pipefail

OWNER=hiteshjoshi1
PROJECT=2
REPO=hiteshjoshi1/capitalOS_core

fields() { gh project field-list "$PROJECT" --owner "$OWNER" --format json; }
project_id() { gh project view "$PROJECT" --owner "$OWNER" --format json --jq .id; }
item_id() {
  gh project item-list "$PROJECT" --owner "$OWNER" --format json --limit 500 \
    --jq ".items[] | select(.content.number == $1) | .id"
}

# set_field <item> <field name> <option prefix>
set_field() {
  local ids
  ids=$(fields | python3 -c '
import json, sys
name, prefix = sys.argv[1], sys.argv[2]
f = next(x for x in json.load(sys.stdin)["fields"] if x["name"] == name)
opts = [o for o in f["options"] if o["name"] == prefix] or [o for o in f["options"] if o["name"].startswith(prefix)]
if len(opts) != 1:
    have = [o["name"] for o in f["options"]]
    sys.exit(f"{name}: no single option matches {prefix!r} (have: {have})")
print(f["id"], opts[0]["id"])' "$2" "$3")
  gh project item-edit --project-id "$(project_id)" --id "$1" \
    --field-id "${ids% *}" --single-select-option-id "${ids#* }" >/dev/null
}

case "${1:-}" in
  list)
    gh project item-list "$PROJECT" --owner "$OWNER" --format json --limit 500 | python3 -c '
import json, sys
want = sys.argv[1] if len(sys.argv) > 1 else None
for it in json.load(sys.stdin)["items"]:
    st = it.get("status") or "-"
    if want and st != want:
        continue
    c = it.get("content", {})
    num, title = c.get("number", "?"), c.get("title", "")
    pri, size = (it.get("priority") or "")[:2], (it.get("size") or "")[:1]
    print(f"#{num:<4} {st:<17} {pri:<3} {size:<2} {title}")' "${2:-}"
    ;;
  add)
    n=${2:?issue number}
    # Use the id item-add returns: item-list lags behind a fresh add. Re-adding is idempotent.
    item=$(gh project item-add "$PROJECT" --owner "$OWNER" --url "https://github.com/$REPO/issues/$n" \
      --format json --jq .id)
    [ -n "${3:-}" ] && set_field "$item" Status "$3"
    [ -n "${4:-}" ] && set_field "$item" Priority "$4"
    [ -n "${5:-}" ] && set_field "$item" Size "$5"
    [ -n "${6:-}" ] && set_field "$item" Kind "$6"
    echo "#$n added${3:+: $3}"
    ;;
  move)
    n=${2:?issue number}; status=${3:?status}
    item=$(item_id "$n")
    [ -n "$item" ] || { echo "#$n is not on the board (board.sh add $n ...)" >&2; exit 1; }
    set_field "$item" Status "$status"
    echo "#$n -> $status"
    ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
