from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.services.scope import ScopePolicyService, derive_verification_support_paths


def _state_with_paths(*planned_paths: str) -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="122",
            slug="navbar-dashboard",
            title="Issue 122",
            task_file="tasks/issue-122-navbar-dashboard.md",
            repo_root=".",
            branch="feature/issue-122-navbar-dashboard",
        ),
        plan_output=PlanOutput(
            summary="Planned frontend work",
            architecture_decisions=[],
            risks=[],
            open_questions=[],
            acceptance_criteria=[],
            planned_paths=list(planned_paths),
            checklist=[],
        ),
    )


def test_derive_verification_support_paths_adds_frontend_test_dirs():
    derived = derive_verification_support_paths(["web/src/App.tsx"])

    assert "web/src/__tests__/" in derived
    assert "web/tests/e2e/" in derived


def test_review_scope_treats_playwright_as_in_scope_for_frontend_tasks():
    state = _state_with_paths("web/src/App.tsx")
    scope = ScopePolicyService(state)

    pending = scope.find_unapproved_extra_files(["web/tests/e2e/home.spec.ts"])

    assert pending == []


def test_rework_autofix_scope_excludes_derived_test_support_paths():
    state = _state_with_paths("web/src/App.tsx", "api/app")
    scope = ScopePolicyService(state)

    allowed = scope.rework_autofix_allowed_paths(["web/src/Dashboard.tsx"])

    assert "web/src/App.tsx" in allowed
    assert "web/src/Dashboard.tsx" in allowed
    assert "web/src/__tests__/" not in allowed
    assert "web/tests/e2e/" not in allowed
    assert "api/tests/" not in allowed
