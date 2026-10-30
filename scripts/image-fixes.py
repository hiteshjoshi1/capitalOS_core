#!/usr/bin/env python3
"""Does a newer release of a pinned image fix its HIGH/CRITICAL findings? (#90, D-18)

For each pinned `repo:tag@sha256:...` ref:
  - candidate = the newest tag in the same major line (majors are deliberate upgrades), or,
    for a tag that isn't a plain version (e.g. python:3.12-slim), what that tag points to now;
  - scan current and candidate with Trivy (fixable HIGH/CRITICAL, remote image source);
  - report what the candidate would clear and what it would add.

Dependabot proposes version bumps only after its 14-day cooldown; a release that clears a
HIGH/CRITICAL goes in at once (D-18), so this surfaces it. Prints a Markdown report; exits 0,
or 3 when some candidate clears findings (so CI can open an issue).

    scripts/image-fixes.py --trivy "$(scripts/tool-image.sh trivy)" <ref> [<ref> ...]

Stdlib only; needs network and Docker (Trivy runs as its pinned image).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
VERSION = re.compile(r"^(v?)(\d+(?:\.\d+)*)$")


def split_ref(ref: str) -> tuple[str, str, str, str]:
    """`repo:tag@digest` -> (registry, repository, tag, digest), Docker Hub defaults filled in."""
    name, _, digest = ref.partition("@")
    name, _, tag = name.rpartition(":") if ":" in name.split("/")[-1] else (name, "", "latest")
    first = name.split("/")[0]
    if "." in first or ":" in first or first == "localhost":
        registry, repo = first, name[len(first) + 1 :]
    else:
        registry, repo = "registry-1.docker.io", name if "/" in name else f"library/{name}"
    return registry, repo, tag, digest


def registry_get(registry: str, path: str, *, head: bool = False) -> tuple[dict, bytes, str]:
    """GET/HEAD against a v2 registry, following the anonymous bearer-token challenge."""
    url = f"https://{registry}{path}"
    headers = {"Accept": MANIFEST_TYPES}
    for _ in range(2):
        req = urllib.request.Request(url, headers=headers, method="HEAD" if head else "GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return dict(resp.headers), (b"" if head else resp.read()), resp.headers.get("Link", "")
        except urllib.error.HTTPError as err:
            challenge = err.headers.get("WWW-Authenticate", "")
            if err.code != 401 or not challenge.lower().startswith("bearer"):
                raise
            params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
            realm = params.pop("realm")
            with urllib.request.urlopen(f"{realm}?{urllib.parse.urlencode(params)}", timeout=30) as tok:
                body = json.load(tok)
            headers["Authorization"] = f"Bearer {body.get('token') or body.get('access_token')}"
    raise RuntimeError(f"unauthorized: {url}")


def list_tags(registry: str, repo: str) -> list[str]:
    tags: list[str] = []
    path = f"/v2/{repo}/tags/list?n=1000"
    while path:
        _, body, link = registry_get(registry, path)
        tags += json.loads(body).get("tags") or []
        match = re.search(r"<([^>]+)>;\s*rel=\"next\"", link)
        path = match.group(1) if match else ""
        if path.startswith("http"):
            path = urllib.parse.urlsplit(path)._replace(scheme="", netloc="").geturl()
    return tags


def candidate(ref: str) -> str | None:
    registry, repo, tag, digest = split_ref(ref)
    image = ref.split("@")[0].rsplit(":", 1)[0]
    match = VERSION.match(tag)
    if not match:
        # A floating tag: has it moved to a newer build?
        headers, _, _ = registry_get(registry, f"/v2/{repo}/manifests/{tag}", head=True)
        now = {k.lower(): v for k, v in headers.items()}.get("docker-content-digest", "")
        return f"{image}:{tag}@{now}" if now and now != digest else None
    prefix, current = match.group(1), tuple(int(x) for x in match.group(2).split("."))
    best = current
    for other in list_tags(registry, repo):
        m = VERSION.match(other)
        if not m or m.group(1) != prefix:
            continue
        version = tuple(int(x) for x in m.group(2).split("."))
        if len(version) == len(current) and version[0] == current[0] and version > best:
            best = version
    if best == current:
        return None
    new_tag = prefix + ".".join(map(str, best))
    headers, _, _ = registry_get(registry, f"/v2/{repo}/manifests/{new_tag}", head=True)
    new_digest = {k.lower(): v for k, v in headers.items()}.get("docker-content-digest", "")
    return f"{image}:{new_tag}@{new_digest}"


def findings(trivy: str, ref: str) -> dict[str, str]:
    """Fixable HIGH/CRITICAL findings: {vuln-id/package: severity}."""
    out = subprocess.run(
        ["docker", "run", "--rm", "-v", "capitalos-trivy-cache:/root/.cache", trivy, "image", "--quiet",
         "--skip-version-check", "--scanners", "vuln", "--ignore-unfixed", "--severity", "HIGH,CRITICAL",
         "--image-src", "remote", "--format", "json", ref],
        capture_output=True, text=True, check=True,
    ).stdout
    found: dict[str, str] = {}
    for result in json.loads(out).get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            found[f"{vuln['VulnerabilityID']} ({vuln['PkgName']})"] = vuln["Severity"]
    return found


def count(found: dict[str, str]) -> str:
    crit = sum(1 for s in found.values() if s == "CRITICAL")
    return f"{crit} CRITICAL / {len(found) - crit} HIGH"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trivy", required=True, help="Trivy image ref (scripts/tool-image.sh trivy)")
    parser.add_argument("refs", nargs="+")
    args = parser.parse_args()

    rows, fixes = [], []
    for ref in args.refs:
        name = ref.split("@")[0]
        try:
            cand = candidate(ref)
            current = findings(args.trivy, ref)
            if cand is None:
                same = "tag still points to this build" if not VERSION.match(split_ref(ref)[2]) else "no newer release in this major line"
                rows.append(f"| `{name}` | {count(current)} | {same} | |")
                continue
            new = findings(args.trivy, cand)
        except Exception as exc:  # noqa: BLE001 - one bad registry shouldn't hide the rest
            rows.append(f"| `{name}` | | check failed: {exc} | |")
            continue
        cleared = sorted(set(current) - set(new))
        added = sorted(set(new) - set(current))
        verdict = f"**clears {len(cleared)}**" if cleared else "clears nothing"
        if added:
            verdict += f", adds {len(added)}"
        rows.append(f"| `{name}` | {count(current)} | `{cand.split('@')[0]}`: {count(new)} | {verdict} |")
        if cleared:
            fixes.append(f"- `{name}` → `{cand}` clears: " + ", ".join(cleared[:12])
                         + (" …" if len(cleared) > 12 else "") + (f"; adds: {', '.join(added[:6])}" if added else ""))

    print("| Image | Now (fixable) | Newest in line | Verdict |\n|---|---|---|---|")
    print("\n".join(rows))
    if fixes:
        print("\n**A newer release fixes HIGH/CRITICAL findings; take it without the 14-day wait (D-18):**")
        print("\n".join(fixes))
        print("\nCheck it with `make verify-image IMAGE=<new ref>`, bump the pin, and put it through the test instance.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
