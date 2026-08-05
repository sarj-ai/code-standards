"""Release orchestration preserves compatibility-bundle publication ordering."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_lint_config_release_waits_for_typescript_and_preflights_registry() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    lint_config_job = workflow.split("  build-lint-configs:", 1)[1].split("  publish-lint-configs:", 1)[0]

    assert "- publish-typescript" in lint_config_job
    assert "libs.release.registry --root ../.." in lint_config_job


def test_release_tags_are_bound_to_successful_publish_sha_and_independent() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    tag_job = workflow.split("  tag:", 1)[1]

    assert "registry existence alone is never treated as proof" in workflow
    assert tag_job.count("always() && needs.publish-") == 6
    assert tag_job.count('--commit "${{ github.sha }}"') == 6
