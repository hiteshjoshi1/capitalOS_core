#!/bin/bash
# The CapitalOS backlog board (GitHub Project #2, owner hiteshjoshi1) from the terminal (#42).
#   board.sh list [STATUS]                          items, optionally only one Status
#   board.sh add <issue#>... [STATUS] [P] [SIZE] [KIND]
#                                                   put issues on the board, e.g.
#                                                   board.sh add 50 51 "Next up" P2 S Ops
#   board.sh move <issue#>... <STATUS>              e.g. board.sh move 359 361 "Fixed-To Review"
# STATUS: "Next up" | "In progress" | "Fixed-To Review" | "Waiting on Hitesh" | Backlog | Done
# P: P0..P3   SIZE: S | M | L   KIND: Ops | Process | Feature | Bug | Security | "Tech debt"
# Option values match by prefix, so P1 matches "P1 High" and S matches "S (under a day)".
# Any number of issues is one or two GitHub calls (#453): IDs are cached, changes are one mutation,
# and a rate-limit answer is retried with back-off. The logic is in scripts/board.py.
set -euo pipefail
exec python3 -I "$(dirname "$0")/board.py" "$@"
