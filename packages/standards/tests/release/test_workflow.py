from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import NamedTuple

import pytest
import yaml

from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


REPO_ROOT = Path(__file__).resolve().parents[4]


class _PreflightResult(NamedTuple):
    process: subprocess.CompletedProcess[str]
    output: str


def _release_tag_preflight_script() -> str:
    return _run("release-tags.yml", "preflight", "Detect tag or GitHub Release recovery")


def _job(filename: str, name: str) -> dict[str, object]:
    document: object = yaml.safe_load((REPO_ROOT / ".github/workflows" / filename).read_text())  # pyright: ignore[reportAny] -- narrow the workflow parser boundary.
    assert is_object_mapping(document)
    jobs = document["jobs"]
    assert is_object_mapping(jobs)
    job = jobs[name]
    assert is_object_mapping(job)
    return {key: value for key, value in job.items() if isinstance(key, str)}


def _steps(filename: str, name: str) -> list[dict[object, object]]:
    steps = _job(filename, name)["steps"]
    assert is_object_list(steps)
    return [step for step in steps if is_object_mapping(step)]


def _run(filename: str, job: str, step_name: str) -> str:
    step = next(step for step in _steps(filename, job) if step.get("name") == step_name)
    command = step["run"]
    assert isinstance(command, str)
    return command


def _checkout_scripts(root: Path) -> None:
    scripts = root / ".github/scripts"
    scripts.parent.mkdir()
    scripts.symlink_to(REPO_ROOT / ".github/scripts", target_is_directory=True)


def _write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _run_release_tag_preflight(
    tmp_path: Path,
    *,
    git_mode: str = "existing",
    http_status: str = "200",
    malformed_manifest: bool = False,
) -> _PreflightResult:
    _checkout_scripts(tmp_path)
    versions = {
        "typescript": "1.0.0",
        "bootstrap": "1.5.0",
        "contracts": "1.0.0",
        "python": "2.0.0",
        "sql": "3.0.0",
        "iac": "4.0.0",
        "standards": "5.0.0",
        "tsconfig": "6.0.0",
    }
    for target, version in versions.items():
        package = tmp_path / "packages" / target
        package.mkdir(parents=True)
        if target in {"typescript", "tsconfig"}:
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
        case "$*" in
          *"maintain release verify-tags --commit $TARGET_SHA") ;;
          *) exit 64 ;;
        esac
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
    lint_config_job = workflow.split("  publish-standards:", 1)[1].split("  build-tsconfig:", 1)[0]

    assert "- publish-typescript" in lint_config_job
    assert "- publish-bootstrap" in lint_config_job
    assert "needs.publish-bootstrap.result == 'success'" in lint_config_job
    assert "maintain release verify-publications" in lint_config_job


@pytest.mark.parametrize("filename", ["release.yml", "release-tags.yml"])
def test_publication_and_tag_recovery_require_security_at_exact_revision(filename: str) -> None:
    job = _job(filename, "release-safety")
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    steps = _steps(filename, "release-safety")
    checkout_index, checkout = next(
        (index, step) for index, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    gate_index, gate = next((index, step) for index, step in enumerate(steps) if "run" in step)
    assert checkout_index < gate_index
    revision = "${{ github.sha }}" if filename == "release.yml" else "${{ github.event.workflow_run.head_sha }}"
    assert checkout["with"] == {"ref": revision, "persist-credentials": False}
    assert gate["env"] == {"GH_TOKEN": "${{ github.token }}", "TARGET_SHA": revision}


def test_release_tags_registry_visible_packages_at_the_published_commit() -> None:
    release = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/release-tags.yml").read_text(encoding="utf-8")

    assert "contents: write" not in release  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "workflow_run:" in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "github.event.workflow_run.conclusion == 'success'" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "github.event.workflow_run.head_branch == 'main'" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "contents: write" in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "\n  preflight:\n" in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "\n  release-safety:\n    needs: preflight\n" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "\n  tag:\n    needs: [preflight, release-safety]\n" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "needs.preflight.outputs.recovery == 'true'" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "needs.release-safety.result == 'success'" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (
        "maintain release create-tags typescript bootstrap contracts python sql iac standards tsconfig" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert '--commit "$PUBLISHED_SHA"' in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract


def test_tsconfig_release_publishes_verified_registry_artifacts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    tsconfig_publish = workflow.split("  publish-tsconfig:", 1)[1]

    assert "needs.build-tsconfig.outputs.artifact_sha256" in tsconfig_publish
    assert "verify_registry_publication.py npm" in tsconfig_publish
    assert "--publish" in tsconfig_publish
    assert "--environment npm-tsconfig-release" in tsconfig_publish


def test_typescript_release_verifies_its_own_registry_artifact() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    publish = workflow.split("  publish-typescript:", 1)[1].split("  build-bootstrap:", 1)[0]

    assert "needs.build-typescript.outputs.artifact_sha256" in publish
    assert "verify_registry_publication.py npm" in publish
    assert "--publish" in publish
    assert "--environment npm-typescript-release" in publish
    assert "needs.build-design" not in publish
    assert "@sarj/design" not in publish


def test_npm_release_reconciles_without_republishing() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    typescript_publish = workflow.split("  publish-typescript:", 1)[1].split("  build-bootstrap:", 1)[0]
    tsconfig_publish = workflow.split("  publish-tsconfig:", 1)[1]

    assert "schedule:" in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert "cron: '17 * * * *'" in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        "BEFORE: ${{ github.event.before || github.sha }}" in workflow
    )
    assert "run: npm publish" not in workflow  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    for publisher in (typescript_publish, tsconfig_publish):
        assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
            "timeout-minutes: 45" in publisher
        )
        assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
            "verify_registry_publication.py npm" in publisher
        )
        assert "--publish" in publisher  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract


def test_npm_tag_recovery_checks_full_history_against_the_current_commit() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        workflow.count("fetch-depth: 0") >= 9
    )
    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        workflow.count("EXPECTED_COMMIT: ${{ github.sha }}") == 2
    )


def test_every_pypi_publish_job_verifies_exact_bytes_and_attestations() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert (  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
        workflow.count("verify_registry_publication.py pypi") == 6
    )
    assert (
        workflow.count("skip-existing: true") == 6
    )  # sarj-noqa: SARJ402 -- workflow text is the release-policy contract
    for project, environment in (
        ("sarj-standards-bootstrap", "pypi-bootstrap-release"),
        ("sarj-rule-contracts", "pypi-contracts-release"),
        ("sarj-python-lint", "pypi-python-release"),
        ("sarj-sql-lint", "pypi-sql-release"),
        ("sarj-iac-lint", "pypi-iac-release"),
    ):
        assert (
            f"--dist verified-dist --project {project}" in workflow
        )  # sarj-noqa: SARJ402 -- workflow text is the publisher contract
        assert (
            f"--environment {environment}" in workflow
        )  # sarj-noqa: SARJ402 -- workflow text is the publisher contract
    assert (
        "--project code-standards --project sarj-standards" in workflow
    )  # sarj-noqa: SARJ402 -- workflow text is the publisher contract
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


@pytest.mark.parametrize("filename", ["release.yml", "release-tags.yml"])
@pytest.mark.parametrize("terminal", [None, "success", "failure", "cancelled", "skipped"])
def test_release_fallback_requires_successful_terminal_ci(tmp_path: Path, filename: str, terminal: str | None) -> None:
    _checkout_scripts(tmp_path)
    jobs = [{"name": "Detect affected checks", "status": "completed", "conclusion": "success"}]
    if terminal is not None:
        jobs.append({"name": "CI complete", "status": "completed", "conclusion": terminal})
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "sleep", "#!/bin/sh\nexit 99\n")
    _write_executable(
        fake_bin / "gh",
        f"""
        #!{sys.executable}
        import json, os, sys
        with open(os.environ['CALLS'], 'a') as log:
            log.write(json.dumps(sys.argv[1:]) + '\\n')
        endpoint = sys.argv[4]
        if endpoint.endswith('/jobs'):
            print(os.environ['JOBS'])
        else:
            run = {{'head_sha': os.environ['TARGET_SHA'], 'event': 'push', 'head_repository': {{'full_name': os.environ['GITHUB_REPOSITORY']}}, 'id': 42, 'conclusion': None if '/ci.yml/' in endpoint else 'success'}}
            wrong_sha = {{**run, 'head_sha': 'b' * 40, 'conclusion': 'success'}}
            wrong_repo = {{**run, 'head_repository': {{'full_name': 'untrusted/repo'}}, 'conclusion': 'success'}}
            print(json.dumps({{'workflow_runs': [wrong_sha, wrong_repo, run]}}))
        """,
    )
    process = subprocess.run(
        (
            "bash",
            "-euo",
            "pipefail",
            "-c",
            _run(filename, "release-safety", "Require successful checks for this exact revision"),
        ),
        cwd=tmp_path,
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "JOBS": json.dumps({"jobs": jobs}),
            "TARGET_SHA": "a" * 40,
            "GITHUB_REPOSITORY": "example/repo",
            "CALLS": str(tmp_path / "calls.jsonl"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert (process.returncode == 0) is (terminal == "success"), process.stderr
    calls = (tmp_path / "calls.jsonl").read_text().splitlines()
    expected = [
        [
            "api",
            "--method",
            "GET",
            f"repos/example/repo/actions/workflows/{workflow}/runs",
            "-f",
            "head_sha=" + "a" * 40,
            "-f",
            "event=push",
            "-f",
            "per_page=10",
        ]
        for workflow in ("repo-ci.yml", "private-refs.yml", "ci.yml")
    ]
    expected.append(["api", "--method", "GET", "repos/example/repo/actions/runs/42/jobs", "-f", "per_page=100"])
    assert [json.loads(call) for call in calls] == expected
