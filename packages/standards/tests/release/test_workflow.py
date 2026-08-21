from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap
from typing import NamedTuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]


class _PreflightResult(NamedTuple):
    process: subprocess.CompletedProcess[str]
    output: str


def _release_tag_preflight_script() -> str:
    workflow = (REPO_ROOT / ".github/workflows/release-tags.yml").read_text(encoding="utf-8")
    recovery_step = workflow.split("      - id: recovery\n", 1)[1].split("\n\n  release-safety:\n", 1)[0]
    return textwrap.dedent(recovery_step.split("        run: |\n", 1)[1])


def _write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    path.chmod(0o755)


def _run_release_tag_preflight(
    tmp_path: Path,
    *,
    git_mode: str = "existing",
    http_status: str = "200",
    malformed_manifest: bool = False,
) -> _PreflightResult:
    versions = {
        "typescript": "1.0.0",
        "bootstrap": "1.5.0",
        "python": "2.0.0",
        "sql": "3.0.0",
        "iac": "4.0.0",
        "standards": "5.0.0",
        "tsconfig": "6.0.0",
        "docs-ui": "0.1.0",
    }
    for target, version in versions.items():
        package = tmp_path / "packages" / target
        package.mkdir(parents=True)
        if target in {"typescript", "tsconfig", "docs-ui"}:
            value = "42" if malformed_manifest and target == "typescript" else f'{{"version":"{version}"}}'
            (package / "package.json").write_text(value, encoding="utf-8")
        else:
            value = (
                "version = 42\n"
                if malformed_manifest and target == "standards"
                else f'[project]\nversion = "{version}"\n'
            )
            (package / "pyproject.toml").write_text(value, encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python3").symlink_to(sys.executable)
    _write_executable(
        fake_bin / "uv",
        """
        #!/bin/sh
        case "$FAKE_GIT_MODE" in
          existing) exit 0 ;;
          missing) exit 1 ;;
          error) exit 2 ;;
          *) exit 64 ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "curl",
        """
        #!/bin/sh
        if [ "$FAKE_HTTP_STATUS" = transport-error ]; then
          exit 7
        fi
        printf '%s' "$FAKE_HTTP_STATUS"
        """,
    )
    _write_executable(
        fake_bin / "jq",
        """
        #!/bin/sh
        while [ "$#" -gt 0 ]; do
          if [ "$1" = value ]; then
            shift
            printf '%s\\n' "$1"
            exit 0
          fi
          shift
        done
        exit 64
        """,
    )

    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    output = tmp_path / "github-output"
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "FAKE_GIT_MODE": git_mode,
        "FAKE_HTTP_STATUS": http_status,
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_OUTPUT": str(output),
        "GH_TOKEN": "test-token",
        "TARGET_SHA": "a" * 40,
        "GITHUB_API_URL": "https://api.github.invalid",
        "GITHUB_REPOSITORY": "sarj-ai/code-standards",
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _release_tag_preflight_script()],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    github_output = output.read_text(encoding="utf-8") if output.exists() else ""
    return _PreflightResult(result, github_output)


def test_lint_config_release_waits_for_typescript_and_preflights_registry() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    lint_config_job = workflow.split("  build-standards:", 1)[1].split("  publish-standards:", 1)[0]

    assert "- publish-typescript" in lint_config_job
    assert "- publish-bootstrap" in lint_config_job
    assert "needs.publish-bootstrap.result == 'success'" in lint_config_job
    assert "maintain release verify-publications" in lint_config_job


def test_release_tags_registry_visible_packages_at_the_published_commit() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/release-tags.yml").read_text(encoding="utf-8")

    assert "contents: write" not in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "workflow_run:" in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    assert "contents: write" in workflow
    assert "\n  preflight:\n" in workflow
    assert "\n  release-safety:\n    needs: preflight\n" in workflow
    assert "\n  tag:\n    needs: [preflight, release-safety]\n" in workflow
    assert "needs.preflight.outputs.recovery == 'true'" in workflow
    assert "needs.release-safety.result == 'success'" in workflow
    for specification in (
        "repo-ci.yml|release-ready",
        "private-refs.yml|private references",
        "bootstrap-ci.yml|bootstrap CI",
        "python-ci.yml|python CI",
        "typescript-ci.yml|typescript CI",
        "sql-ci.yml|sql CI",
        "iac-ci.yml|iac CI",
        "tsconfig-ci.yml|tsconfig CI",
        "docs-ui-ci.yml|docs UI CI",
        "standards-ci.yml|standards CI",
    ):
        assert specification in workflow
    assert "head_repository.full_name == $repo" in workflow
    assert "actions/runs/$run_id/jobs" in workflow
    assert "pending_jobs == 0 && successful_jobs > 0" in workflow
    assert "maintain release create-tags typescript bootstrap python sql iac standards tsconfig docs-ui" in workflow
    assert '--commit "$PUBLISHED_SHA"' in workflow
    assert 'maintain release verify-tags --commit "$TARGET_SHA"' in workflow


def test_additional_npm_releases_publish_verified_registry_artifacts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    build = workflow.split("  build-docs-ui:", 1)[1].split("  publish-docs-ui:", 1)[0]
    publish = workflow.split("  publish-docs-ui:", 1)[1]
    tsconfig_publish = workflow.split("  publish-tsconfig:", 1)[1].split("  build-docs-ui:", 1)[0]

    assert "needs.detect.outputs.docs_ui == 'true'" in build
    assert "test \"$actual_name\" = '@sarj/docs-ui'" in build
    assert "name: npm-docs-ui" in build
    assert "environment: npm-docs-ui-release" in publish
    assert "needs.build-docs-ui.outputs.artifact_sha256" in publish
    assert 'npm publish "$RUNNER_TEMP/npm-artifacts/package.tgz"' in publish
    assert "verify_registry_publication.py npm" in publish
    assert "--environment npm-docs-ui-release" in publish
    assert '--commit "$EXPECTED_COMMIT"' in publish
    assert "needs.build-tsconfig.outputs.artifact_sha256" in tsconfig_publish
    assert "verify_registry_publication.py npm" in tsconfig_publish
    assert "--environment npm-tsconfig-release" in tsconfig_publish


def test_typescript_release_verifies_its_own_registry_artifact() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    publish = workflow.split("  publish-typescript:", 1)[1].split("  build-bootstrap:", 1)[0]

    assert "needs.build-typescript.outputs.artifact_sha256" in publish
    assert "verify_registry_publication.py npm" in publish
    assert "--environment npm-typescript-release" in publish
    assert "needs.build-docs-ui" not in publish
    assert "@sarj/docs-ui" not in publish


def test_every_pypi_publish_job_verifies_exact_bytes_and_attestations() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        workflow.count("verify_registry_publication.py pypi") == 5
    )
    assert workflow.count("skip-existing: true") == 5
    for project, environment in (
        ("sarj-standards-bootstrap", "pypi-bootstrap-release"),
        ("sarj-python-lint", "pypi-python-release"),
        ("sarj-sql-lint", "pypi-sql-release"),
        ("sarj-iac-lint", "pypi-iac-release"),
    ):
        assert f"--dist verified-dist --project {project}" in workflow
        assert f"--environment {environment}" in workflow
    assert "--project code-standards --project sarj-standards" in workflow
    assert (  # sarj-noqa: SARJ402 -- verifier text is the pinned supply-chain contract
        "pypi-attestations==0.0.30"
        in (REPO_ROOT / ".github/scripts/verify_registry_publication.py").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    ("git_mode", "http_status", "expected_recovery"),
    [
        ("existing", "200", "false"),
        ("missing", "200", "true"),
        ("existing", "404", "true"),
    ],
)
def test_release_tag_preflight_classifies_only_confirmed_recovery(
    tmp_path: Path,
    git_mode: str,
    http_status: str,
    expected_recovery: str,
) -> None:
    result, output = _run_release_tag_preflight(
        tmp_path,
        git_mode=git_mode,
        http_status=http_status,
    )

    assert result.returncode == 0, result.stderr
    assert f"recovery={expected_recovery}\n" in output
    assert "standards_tag=standards-v5.0.0\n" in output


@pytest.mark.parametrize(
    ("git_mode", "http_status"),
    [
        ("error", "200"),
        ("existing", "403"),
        ("existing", "500"),
        ("existing", "transport-error"),
    ],
)
def test_release_tag_preflight_fails_closed_on_operational_errors(
    tmp_path: Path,
    git_mode: str,
    http_status: str,
) -> None:
    result, output = _run_release_tag_preflight(
        tmp_path,
        git_mode=git_mode,
        http_status=http_status,
    )

    assert result.returncode != 0
    assert not output


def test_release_tag_preflight_rejects_malformed_manifest(tmp_path: Path) -> None:
    result, output = _run_release_tag_preflight(tmp_path, malformed_manifest=True)

    assert result.returncode != 0
    assert not output
