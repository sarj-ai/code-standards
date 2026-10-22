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
    branch = "${{ github.ref_name }}" if filename == "release.yml" else "${{ github.event.workflow_run.head_branch }}"
    assert gate["env"] == {"GH_TOKEN": "${{ github.token }}", "TARGET_SHA": revision, "TARGET_BRANCH": branch}


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


def test_maintenance_uses_its_successful_publisher_identity_and_never_rolls_out() -> None:
    preflight = _steps("release-tags.yml", "preflight")
    lane_index, lane = next((index, step) for index, step in enumerate(preflight) if step.get("id") == "lane")
    recovery_index = next(index for index, step in enumerate(preflight) if step.get("id") == "recovery")
    assert lane_index < recovery_index
    assert lane["env"] == {
        "SOURCE_REF": "refs/heads/${{ github.event.workflow_run.head_branch }}",
        "SOURCE_SHA": "${{ github.event.workflow_run.head_sha }}",
        "CONTROLLER_SHA": "${{ github.workflow_sha }}",
    }
    dispatch = _job("release-tags.yml", "dispatch-rollout")
    assert "needs.preflight.outputs.lane == 'main'" in str(dispatch["if"])
    tag_steps = _steps("release-tags.yml", "tag")
    maintenance = next(step for step in tag_steps if step.get("name") == "Create only the maintenance Standards tag")
    assert maintenance["if"] == "needs.preflight.outputs.lane == 'standards-maintenance'"
    assert maintenance["env"] == {"PUBLISHED_SHA": "${{ github.event.workflow_run.head_sha }}"}
    assert 'create-tags standards --commit "$PUBLISHED_SHA"' in str(maintenance["run"])


def test_maintenance_publication_keeps_fresh_build_and_prevents_sibling_publication() -> None:
    detect = _steps("release.yml", "detect")
    lane_index = next(index for index, step in enumerate(detect) if step.get("id") == "lane")
    targets_index = next(index for index, step in enumerate(detect) if step.get("id") == "c")
    guard_index, guard = next(
        (index, step)
        for index, step in enumerate(detect)
        if step.get("name") == "Reject maintenance sibling publication"
    )
    assert lane_index < targets_index < guard_index
    assert guard["if"] == "steps.lane.outputs.lane == 'standards-maintenance'"
    build = _steps("release.yml", "build-standards")
    reuse = next(step for step in build if step.get("id") == "reuse")
    assert reuse["if"] == "needs.detect.outputs.lane == 'main'"
    for name in [
        "Build package and exact local dependency wheels",
        "Build the plugin for native ESLint integration tests",
        "Install the manifest formatter",
        "Install the pinned native tool bootstrap",
        "Install and attest integration native tools",
        "Test against the built wheel",
        "Smoke test the source distribution",
    ]:
        step = next(step for step in build if step.get("name") == name)
        assert step["if"] == "steps.reuse.outputs.reused != 'true'"
    names = [step.get("name") for step in build]
    assert names.index("Install the rule authoring parser") < names.index(
        "Build the plugin for native ESLint integration tests"
    )
    assert names.index("Build the plugin for native ESLint integration tests") < names.index(
        "Test against the built wheel"
    )
    assert names.index("Install the manifest formatter") < names.index("Test against the built wheel")
    publish = _job("release.yml", "publish-standards")
    assert publish["environment"] == "pypi-standards-release"
    assert publish["permissions"] == {"contents": "read", "id-token": "write"}


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
            run = {{'head_sha': os.environ['TARGET_SHA'], 'head_branch': os.environ['TARGET_BRANCH'], 'event': 'push', 'path': '.github/workflows/' + endpoint.split('/workflows/')[1].split('/')[0], 'head_repository': {{'full_name': os.environ['GITHUB_REPOSITORY']}}, 'id': 42, 'conclusion': None if '/ci.yml/' in endpoint else 'success'}}
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
            "TARGET_BRANCH": "main",
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


class _LaneCheckout(NamedTuple):
    root: Path
    legacy_sha: str
    controller_sha: str
    runner_temp: Path
    binaries: Path


def _lane_git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            *arguments,
        ),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


@pytest.fixture
def lane_checkout(tmp_path: Path) -> _LaneCheckout:
    root = tmp_path / "publisher"
    root.mkdir()
    _lane_git(root, "init", "--quiet")
    (root / "publication.txt").write_text("older main publication\n")
    _lane_git(root, "add", ".")
    _lane_git(root, "commit", "--quiet", "-m", "older main without the lane helper")
    legacy_sha = _lane_git(root, "rev-parse", "HEAD")
    helper = root / ".github/scripts/release_lane.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes((REPO_ROOT / ".github/scripts/release_lane.py").read_bytes())
    _lane_git(root, "add", ".")
    _lane_git(root, "commit", "--quiet", "-m", "trusted workflow controller")
    controller_sha = _lane_git(root, "rev-parse", "HEAD")
    _lane_git(root, "checkout", "--quiet", "--detach", legacy_sha)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    _write_executable(
        binaries / "uv",
        """
        #!/bin/sh
        [ "$1" = run ] && [ "$2" = --script ] || exit 64
        shift 2
        exec "$FIXTURE_PYTHON" "$@"
        """,
    )
    return _LaneCheckout(root, legacy_sha, controller_sha, runner_temp, binaries)


@pytest.mark.parametrize(
    ("scenario", "source_ref", "expected_status"),
    [
        ("legacy-main", "refs/heads/main", 0),
        ("current-main", "refs/heads/main", 0),
        ("untrusted-maintenance-helper", "refs/heads/maintenance/standards-8.101", 2),
        ("wrong-source-sha", "refs/heads/main", 2),
        ("missing-maintenance-helper", "refs/heads/maintenance/standards-8.101", 2),
        ("missing-feature-helper", "refs/heads/feature/release", 2),
        ("missing-controller", "refs/heads/main", 128),
        ("symbolic-controller", "refs/heads/main", 1),
        ("maintenance-source", "refs/heads/maintenance/standards-8.101", 2),
        ("feature-source", "refs/heads/feature/release", 2),
    ],
)
def test_tag_lane_runs_the_yaml_step_against_the_exact_publisher_checkout(
    lane_checkout: _LaneCheckout, scenario: str, source_ref: str, expected_status: int
) -> None:
    source_helper = scenario in {"current-main", "maintenance-source", "feature-source", "untrusted-maintenance-helper"}
    source_sha = lane_checkout.controller_sha if source_helper else lane_checkout.legacy_sha
    if source_helper:
        _lane_git(lane_checkout.root, "checkout", "--quiet", "--detach", source_sha)
    if scenario == "untrusted-maintenance-helper":
        helper = lane_checkout.root / ".github/scripts/release_lane.py"
        helper.write_text("from pathlib import Path\nPath('untrusted-helper-executed').touch()\n")
        _lane_git(lane_checkout.root, "add", ".")
        _lane_git(lane_checkout.root, "commit", "--quiet", "-m", "untrusted candidate helper")
        source_sha = _lane_git(lane_checkout.root, "rev-parse", "HEAD")
    controller_sha = lane_checkout.controller_sha
    if scenario == "missing-controller":
        controller_sha = "b" * 40
    elif scenario == "symbolic-controller":
        controller_sha = "HEAD"
    if scenario == "wrong-source-sha":
        source_sha = "a" * 40
    output = lane_checkout.runner_temp / "github-output"
    result = subprocess.run(
        (
            "bash",
            "-euo",
            "pipefail",
            "-c",
            _run("release-tags.yml", "preflight", "Validate the successful publisher's exact source lane"),
        ),
        cwd=lane_checkout.root,
        env={
            "PATH": f"{lane_checkout.binaries}:/usr/bin:/bin",
            "FIXTURE_PYTHON": sys.executable,
            "SOURCE_REF": source_ref,
            "SOURCE_SHA": source_sha,
            "CONTROLLER_SHA": controller_sha,
            "RUNNER_TEMP": str(lane_checkout.runner_temp),
            "GITHUB_OUTPUT": str(output),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected_status, result.stderr
    assert (lane_checkout.root / ".github/scripts/release_lane.py").exists() is source_helper
    assert not _lane_git(lane_checkout.root, "status", "--porcelain=v1")
    if expected_status == 0:
        assert output.read_text() == "lane=main\n"
        assert f"publication at {source_sha}" in result.stdout
    else:
        assert not output.exists()
    materialized = lane_checkout.runner_temp / "release-lane-controller.py"
    assert not (lane_checkout.root / "untrusted-helper-executed").exists()
    if scenario not in {"missing-controller", "symbolic-controller"}:
        assert materialized.is_file()
        assert (  # sarj-noqa: SARJ402 -- exact materialized controller bytes are the source-binding trust contract.
            materialized.read_bytes() == (REPO_ROOT / ".github/scripts/release_lane.py").read_bytes()
        )
    elif scenario == "symbolic-controller":
        assert not materialized.exists()
