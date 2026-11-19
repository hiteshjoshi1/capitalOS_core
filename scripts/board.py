#!/usr/bin/env python3
"""The CapitalOS backlog board (GitHub Project #2) from the terminal (#42, #453). Called by scripts/board.sh.

Few GitHub calls (#453: the old script made ~4 per issue, one a full item-list, and tripped GitHub's
secondary rate limit): the project and field/option IDs are cached in a file, the issues' board items are
looked up in one query, and every change for any number of issues goes in one GraphQL mutation. A
rate-limit answer is retried with back-off.

Env (for tests): BOARD_GH (gh binary), BOARD_CACHE (cache file), BOARD_BACKOFF (first wait, seconds).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

OWNER = "hiteshjoshi1"
PROJECT = 2
REPO_OWNER, REPO_NAME = "hiteshjoshi1", "capitalOS_core"
CACHE_TTL_S = 7 * 24 * 3600
FIELDS = ("Status", "Priority", "Size", "Kind")  # positional order after the issue numbers in `add`

GH = os.environ.get("BOARD_GH", "gh")
CACHE = Path(os.environ.get("BOARD_CACHE") or Path.home() / ".cache" / "capitalos" / "board-ids.json")
BACKOFF = float(os.environ.get("BOARD_BACKOFF", "5"))
TRIES = 5
RATE_LIMITED = re.compile(r"rate limit|secondary|abuse|HTTP 403|HTTP 429|HTTP 502|was submitted too quickly", re.I)

USAGE = """\
board.sh list [STATUS]                          items, optionally only one Status
board.sh add <issue#>... [STATUS] [P] [SIZE] [KIND]
                                                put issues on the board, e.g.
                                                board.sh add 50 51 "Next up" P2 S Ops
board.sh move <issue#>... <STATUS>              e.g. board.sh move 359 361 "Fixed-To Review"
STATUS: "Next up" | "In progress" | "Fixed-To Review" | "Waiting on Hitesh" | Backlog | Done
P: P0..P3   SIZE: S | M | L   KIND: Ops | Process | Feature | Bug | Security | "Tech debt"
Option values match by prefix, so P1 matches "P1 High" and S matches "S (under a day)".
Each command is one or two GitHub calls whatever the number of issues; IDs are cached in
~/.cache/capitalos/board-ids.json (deleted and refetched when stale)."""


class BoardError(Exception):
    pass


def gh(*args: str) -> str:
    """Run gh, retrying with exponential back-off while GitHub answers with a rate limit."""
    wait = BACKOFF
    for attempt in range(1, TRIES + 1):
        p = subprocess.run([GH, *args], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        if attempt < TRIES and RATE_LIMITED.search(p.stderr + p.stdout):
            print(f"GitHub rate limit; retrying in {wait:g}s ({attempt}/{TRIES - 1})", file=sys.stderr)
            time.sleep(wait)
            wait *= 2
            continue
        raise BoardError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {(p.stderr or p.stdout).strip()}")
    raise AssertionError("unreachable")


def graphql(query: str) -> dict:
    out = json.loads(gh("api", "graphql", "-f", f"query={query}"))
    if out.get("errors"):
        raise BoardError("; ".join(e.get("message", str(e)) for e in out["errors"]))
    return out["data"]


def q(s: str) -> str:
    return json.dumps(s)  # a GraphQL string literal


def load_meta(refresh: bool = False) -> dict:
    """{"project": id, "fields": {name: {"id": id, "options": {name: id}}}}, from the cache when fresh."""
    if not refresh:
        try:
            meta = json.loads(CACHE.read_text())
            if time.time() - meta["fetched_at"] < CACHE_TTL_S:
                return meta
        except (OSError, ValueError, KeyError):
            pass
    data = graphql(
        f"query{{user(login:{q(OWNER)}){{projectV2(number:{PROJECT}){{id fields(first:50){{nodes{{"
        "... on ProjectV2SingleSelectField{id name options{id name}}}}}}}"
    )
    proj = data["user"]["projectV2"]
    meta = {
        "fetched_at": time.time(),
        "project": proj["id"],
        "fields": {
            f["name"]: {"id": f["id"], "options": {o["name"]: o["id"] for o in f["options"]}}
            for f in proj["fields"]["nodes"]
            if f and "options" in f
        },
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(meta))
    return meta


def option(meta: dict, field: str, prefix: str) -> tuple[str, str]:
    f = meta["fields"].get(field)
    if not f:
        raise BoardError(f"no field {field!r} on the board")
    opts = [n for n in f["options"] if n == prefix] or [n for n in f["options"] if n.startswith(prefix)]
    if len(opts) != 1:
        raise BoardError(f"{field}: no single option matches {prefix!r} (have: {list(f['options'])})")
    return f["id"], f["options"][opts[0]]


def lookup(meta: dict, numbers: list[int]) -> dict[int, dict]:
    """One query: each issue's node id and its item on this board (None when not on it)."""
    parts = " ".join(
        f"i{n}:issue(number:{n}){{id projectItems(first:20){{nodes{{id project{{id}}}}}}}}" for n in numbers
    )
    data = graphql(f"query{{repository(owner:{q(REPO_OWNER)},name:{q(REPO_NAME)}){{{parts}}}}}")["repository"]
    found = {}
    for n in numbers:
        issue = data.get(f"i{n}")
        if not issue:
            raise BoardError(f"#{n}: no such issue in {REPO_OWNER}/{REPO_NAME}")
        item = next((i["id"] for i in issue["projectItems"]["nodes"] if i["project"]["id"] == meta["project"]), None)
        found[n] = {"issue": issue["id"], "item": item}
    return found


def set_fields(meta: dict, edits: list[tuple[int, str, list[tuple[str, str]]]]) -> None:
    """One mutation for every (issue, item, [(field, option prefix)])."""
    parts = []
    for n, item, pairs in edits:
        for k, (field, prefix) in enumerate(pairs):
            fid, oid = option(meta, field, prefix)
            parts.append(
                f"m{n}_{k}:updateProjectV2ItemFieldValue(input:{{projectId:{q(meta['project'])},itemId:{q(item)},"
                f"fieldId:{q(fid)},value:{{singleSelectOptionId:{q(oid)}}}}}){{clientMutationId}}"
            )
    if parts:
        graphql("mutation{" + " ".join(parts) + "}")


def with_fresh_meta(fn):
    """Run fn(meta); if the cached IDs are stale (a renamed option, a deleted field), refetch once and retry."""
    meta = load_meta()
    try:
        return fn(meta)
    except BoardError as e:
        if time.time() - meta["fetched_at"] < 5:  # just fetched: not a cache problem
            raise
        print(f"retrying with fresh board IDs ({e})", file=sys.stderr)
        return fn(load_meta(refresh=True))


def split_numbers(args: list[str]) -> tuple[list[int], list[str]]:
    nums = []
    while args and re.fullmatch(r"#?\d+", args[0]):
        nums.append(int(args.pop(0).lstrip("#")))
    return nums, args


def cmd_list(args: list[str]) -> None:
    want = args[0] if args else None
    out = gh("project", "item-list", str(PROJECT), "--owner", OWNER, "--format", "json", "--limit", "500")
    for it in json.loads(out)["items"]:
        st = it.get("status") or "-"
        if want and st != want:
            continue
        c = it.get("content", {})
        num, title = c.get("number", "?"), c.get("title", "")
        pri, size = (it.get("priority") or "")[:2], (it.get("size") or "")[:1]
        print(f"#{num:<4} {st:<17} {pri:<3} {size:<2} {title}")


def cmd_move(args: list[str]) -> None:
    nums, rest = split_numbers(args)
    if not nums or len(rest) != 1:
        raise BoardError("usage: board.sh move <issue#>... <STATUS>")
    status = rest[0]

    def run(meta):
        option(meta, "Status", status)  # fail on a bad status before any lookup
        items = lookup(meta, nums)
        missing = [n for n in nums if not items[n]["item"]]
        if missing:
            raise SystemExit(
                "not on the board: " + " ".join(f"#{n}" for n in missing) + " (board.sh add <n> ...); nothing moved"
            )
        set_fields(meta, [(n, items[n]["item"], [("Status", status)]) for n in nums])

    with_fresh_meta(run)
    for n in nums:
        print(f"#{n} -> {status}")


def cmd_add(args: list[str]) -> None:
    nums, rest = split_numbers(args)
    if not nums or len(rest) > len(FIELDS):
        raise BoardError("usage: board.sh add <issue#>... [STATUS] [P] [SIZE] [KIND]")
    pairs = [(f, v) for f, v in zip(FIELDS, rest) if v]

    def run(meta):
        for f, v in pairs:
            option(meta, f, v)
        items = lookup(meta, nums)
        new = [n for n in nums if not items[n]["item"]]
        if new:
            parts = " ".join(
                f"a{n}:addProjectV2ItemById(input:{{projectId:{q(meta['project'])},contentId:{q(items[n]['issue'])}}})"
                "{item{id}}"
                for n in new
            )
            added = graphql("mutation{" + parts + "}")
            for n in new:
                items[n]["item"] = added[f"a{n}"]["item"]["id"]
        set_fields(meta, [(n, items[n]["item"], pairs) for n in nums])

    with_fresh_meta(run)
    for n in nums:
        print(f"#{n} added" + (f": {rest[0]}" if rest and rest[0] else ""))


def main(argv: list[str]) -> int:
    cmds = {"list": cmd_list, "add": cmd_add, "move": cmd_move}
    if not argv or argv[0] not in cmds:
        print(USAGE)
        return 2
    try:
        cmds[argv[0]](argv[1:])
    except BoardError as e:
        print(f"board.sh: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
