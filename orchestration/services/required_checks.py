from __future__ import annotations

from typing import Iterable


REQUIRED_CHECK_CATALOG: dict[str, str] = {
    "ui.app_shell.nav_visibility": "App shell navigation landmark and primary sidebar links remain visible and reachable.",
    "ui.sidebar.default_collapsed": "Sidebar sections default to collapsed when they are not the active route.",
    "ui.theme_toggle.accessible_name": "Theme toggle keeps the stable accessible name expected by tests and e2e flows.",
    "ui.dashboard.exposure_labels": "Dashboard exposure cards keep stable labels and CTA accessible names.",
    "api.health.contract": "Health endpoint returns the stable success contract.",
    "api.dashboard.summary_contract": "Dashboard summary keeps the stable response contract used by the app shell and tests.",
    "state.human_review_restore_roundtrip": "Interrupted human-review workflow state can be exported and restored without stage drift.",
}


def normalize_required_checks(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        check_id = value.strip()
        if not check_id:
            continue
        if check_id not in REQUIRED_CHECK_CATALOG:
            raise ValueError(f"Unknown required check: {check_id}")
        if check_id in seen:
            continue
        seen.add(check_id)
        normalized.append(check_id)
    return normalized


def describe_required_checks(values: Iterable[str]) -> list[str]:
    return [
        f"{check_id}: {REQUIRED_CHECK_CATALOG[check_id]}"
        for check_id in normalize_required_checks(values)
    ]
