from __future__ import annotations

import ast
from pathlib import Path
from typing import TypeGuard

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "standards-rollout.yml"


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _load_yaml(path: Path) -> object:
    parsed: object = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)  # pyright: ignore[reportAny]
    return parsed


def _workflow() -> dict[str, object]:
    parsed = _load_yaml(WORKFLOW)
    assert _is_object(parsed)
    return parsed


def _rendered_workflow() -> str:
    values: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            values.append(value)
        elif _is_array(value):
            for item in value:
                collect(item)
        elif _is_object(value):
            for key, item in value.items():
                values.append(key)
                collect(item)

    collect(_workflow())
    return "\n".join(values)


def _controller_literals() -> frozenset[str]:
    tree = ast.parse(
        (REPO_ROOT / "packages/standards/src/sarj_standards/libs/release/rollout.py").read_text(encoding="utf-8")
    )
    return frozenset(
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_rollout_is_downstream_of_release_and_reconciles_hourly() -> None:
    workflow = _workflow()
    trigger = workflow.get("on")
    assert _is_object(trigger)

    assert set(trigger) == {"workflow_run", "schedule", "workflow_dispatch"}
    assert trigger["workflow_run"] == {"workflows": ["release-tags"], "types": ["completed"]}
    assert trigger["schedule"] == [{"cron": "17 * * * *"}]
    rendered = _rendered_workflow()
    assert "github.event.workflow_run.conclusion == 'success'" in rendered
    assert "github.event.workflow_run.head_branch == 'main'" in rendered
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in rendered
    release = _load_yaml(REPO_ROOT / ".github/workflows/release.yml")
    assert _is_object(release)
    release_trigger = release.get("on")
    assert _is_object(release_trigger)
    assert "workflow_run" not in release_trigger


def test_rollout_uses_one_deterministic_interface_for_every_entrypoint() -> None:
    workflow = _rendered_workflow()

    module = "python -m sarj_standards.libs.release.rollout"
    assert f'{module} --registry "$registry" plan --version "$VERSION"' in workflow
    assert f'{module} --registry "$registry" apply --version "$VERSION"' in workflow
    assert f'{module} --registry "$registry" reconcile --version "$VERSION"' in workflow
    assert "--refresh-package sarj-standards --from sarj-standards" in workflow
    assert f'{module} --registry "$registry" status --version "$VERSION"' in workflow
    assert "github.event.workflow_run.head_sha || github.sha" in workflow
    assert "packages/standards/pyproject.toml" in workflow
    assert "gh auth setup-git" in workflow
    assert 'git config --global user.name "sarj-standards-rollout[bot]"' in workflow


def test_rollout_bootstrap_obeys_the_selected_action_policy() -> None:
    workflow = _rendered_workflow()

    assert "jdx/mise-action" not in workflow
    assert "mise-v${MISE_VERSION}-linux-x64" in workflow
    assert "2026.8.8" in workflow
    assert "1fce52a3656cf14bef6feeb9f0b90d545126a0bb598f0a69afbb9e4702f8f3e3" in workflow
    assert "sha256sum --check --strict" in workflow


def test_rollout_token_is_installation_scoped_and_never_persisted_by_checkout() -> None:
    workflow = _rendered_workflow()
    controller_literals = _controller_literals()

    assert "persist-credentials\nfalse" in workflow
    assert "STANDARDS_ROLLOUT_APP_ID" in workflow
    assert "STANDARDS_ROLLOUT_APP_PRIVATE_KEY" in workflow
    assert "STANDARDS_ROLLOUT_REGISTRY_TOML" in workflow
    assert "repositories\n" not in workflow
    assert "permission-issues" not in workflow
    assert "permission-contents\nwrite" in workflow
    assert "permission-pull-requests\nwrite" in workflow
    assert "permission-workflows\nwrite" in workflow
    assert "issues\nwrite" in workflow
    assert "git push" not in workflow
    assert {"GH_TOKEN", "GITHUB_TOKEN"}.issubset(controller_literals)
    assert "STANDARDS_ROLLOUT_" in controller_literals


def test_failure_is_reported_durably_without_blocking_publication() -> None:
    workflow = _rendered_workflow()
    release = _load_yaml(REPO_ROOT / ".github/workflows/release.yml")
    assert _is_object(release)

    assert "[Standards rollout] $VERSION" in workflow
    assert "gh issue create" in workflow
    assert "gh issue edit" in workflow
    assert "gh issue reopen" in workflow
    assert "gh issue close" in workflow
    assert 'tail -c 40000 "$log"' in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "Enforce the rollout result" in workflow
    assert "Standards rollout is incomplete" in workflow
    release_trigger = release.get("on")
    assert _is_object(release_trigger)
    assert "workflow_run" not in release_trigger
