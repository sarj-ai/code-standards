"""Release orchestration preserves compatibility-bundle publication ordering."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_lint_config_release_waits_for_typescript_and_preflights_registry() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    lint_config_job = workflow.split("  build-standards:", 1)[1].split("  publish-standards:", 1)[0]

    assert "- publish-typescript" in lint_config_job
    assert "maintain release verify-publications" in lint_config_job


def test_release_tags_registry_visible_packages_at_the_published_commit() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/release-tags.yml").read_text(encoding="utf-8")

    assert "contents: write" not in release
    assert "workflow_run:" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    assert "contents: write" in workflow
    assert "\n  preflight:\n" in workflow
    assert "\n  release-safety:\n    needs: preflight\n" in workflow
    assert "\n  tag:\n    needs: [preflight, release-safety]\n" in workflow
    assert "needs.preflight.outputs.recovery == 'true'" in workflow
    assert "needs.release-safety.result == 'success'" in workflow
    assert "repo-ci.yml|release-ready" in workflow
    assert "private-refs.yml|private references" in workflow
    assert "head_repository.full_name == $repo" in workflow
    assert "maintain release create-tags typescript python sql iac standards tsconfig" in workflow
    assert '--commit "$PUBLISHED_SHA"' in workflow
