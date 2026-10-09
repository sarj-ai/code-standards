from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TypeGuard

from pydantic import RootModel
import pytest
import yaml

from sarj_standards.libs.release.process import credential_free_environment
from sarj_standards.libs.typed_containers import is_object_mapping


REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "standards-rollout.yml"


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return is_object_mapping(value) and all(isinstance(key, str) for key in value)


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


def test_rollout_is_downstream_of_release_and_reconciles_every_fifteen_minutes() -> None:
    workflow = _workflow()
    trigger = workflow.get("on")
    assert _is_object(trigger)

    assert set(trigger) == {"schedule", "workflow_dispatch"}
    assert trigger["schedule"] == [{"cron": "7,22,37,52 * * * *"}]
    dispatch = trigger["workflow_dispatch"]
    assert _is_object(dispatch)
    inputs = dispatch["inputs"]
    assert _is_object(inputs)
    version = inputs["version"]
    assert _is_object(version)
    assert version["required"] == "true"
    rendered = _rendered_workflow()
    assert "github.event.workflow_run" not in rendered
    release = _load_yaml(REPO_ROOT / ".github/workflows/release.yml")
    assert _is_object(release)
    release_trigger = release.get("on")
    assert _is_object(release_trigger)
    assert "workflow_run" not in release_trigger


def test_rollout_worker_uses_validated_per_consumer_hosts_with_the_existing_default() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert _is_object(jobs)
    job = jobs["rollout"]
    assert _is_object(job)

    assert job["runs-on"] == "${{ matrix.consumer.workflow_runner || 'ubuntu-latest' }}"
    assert "workflow_runner" in _controller_literals()


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


def test_release_tags_dispatches_rollout_from_the_immutable_release_tag() -> None:
    workflow = _load_yaml(REPO_ROOT / ".github/workflows/release-tags.yml")
    assert _is_object(workflow)
    jobs = workflow.get("jobs")
    assert _is_object(jobs)
    dispatch = jobs.get("dispatch-rollout")
    assert _is_object(dispatch)
    permissions = dispatch.get("permissions")
    assert _is_object(permissions)
    assert permissions.get("actions") == "write"
    assert permissions.get("contents") == "read"
    assert dispatch.get("needs") == ["preflight", "release-safety", "tag"]
    condition = dispatch.get("if")
    assert isinstance(condition, str)
    assert "needs.preflight.outputs.recovery == 'false'" in condition
    assert "needs.release-safety.result == 'success'" in condition
    assert "needs.tag.result == 'success'" in condition
    steps = dispatch.get("steps")
    assert _is_array(steps)
    assert len(steps) == 3
    harden = steps[0]
    assert _is_object(harden)
    assert harden.get("uses") == "step-security/harden-runner@e14015d583714f6e62063499dc959a02595150a1"
    checkout = steps[1]
    assert _is_object(checkout)
    assert checkout["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    options = checkout["with"]
    assert _is_object(options)
    assert options["ref"] == "${{ github.sha }}"
    assert options["persist-credentials"] == "false"
    step = steps[2]
    assert _is_object(step)
    command = step.get("run")
    assert isinstance(command, str)
    assert command == "bash .github/scripts/dispatch-standards-rollout.sh"
    command = _release_dispatch_command()
    assert 'version="${STANDARDS_TAG#standards-v}"' in command
    assert "gh workflow run standards-rollout.yml" in command
    assert '--repo "$GITHUB_REPOSITORY"' in command
    assert '--ref "$STANDARDS_TAG"' in command
    assert '-f version="$version"' in command


@pytest.mark.parametrize("failure", ["", "list", "compare", "cancel", "published"])
def test_publication_supersedes_only_older_automatic_controllers(tmp_path: Path, failure: str) -> None:
    published = "invalid" if failure == "published" else "e" * 40
    records = [
        {"databaseId": 1, "event": "schedule", "status": "in_progress", "headSha": "a" * 40},
        {"databaseId": 2, "event": "schedule", "status": "pending", "headSha": published},
        {"databaseId": 3, "event": "schedule", "status": "in_progress", "headSha": "b" * 40},
        {"databaseId": 4, "event": "schedule", "status": "queued", "headSha": "c" * 40},
        {"databaseId": 5, "event": "workflow_dispatch", "status": "in_progress", "headSha": "a" * 40},
        {"databaseId": 6, "event": "schedule", "status": "completed", "headSha": "a" * 40},
        {"databaseId": 7, "event": "schedule", "status": "pending", "headSha": "invalid"},
        {"databaseId": "invalid", "event": "schedule", "status": "pending", "headSha": "a" * 40},
        {"databaseId": 8, "event": "schedule", "status": "pending", "headSha": "a" * 40},
        {"databaseId": 9, "event": "workflow_dispatch", "status": "in_progress", "headSha": "a" * 40},
        {"databaseId": 10, "event": "workflow_dispatch", "status": "in_progress", "headSha": "a" * 40},
        {"databaseId": 11, "event": "workflow_dispatch", "status": "in_progress", "headSha": "a" * 40},
    ]
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps(records), encoding="utf-8")
    events = tmp_path / "events.txt"
    stub = r"""
gh() {
  if [[ "$1 $2" == 'run list' ]]; then
    [[ "$FAILURE" != list ]] || return 17
    cat "$RUNS"
  elif [[ "$1" == api ]]; then
    [[ "$FAILURE" != compare ]] || return 19
    case "$2" in
      */actions/runs/9) printf '{"event":"workflow_dispatch","head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","head_branch":"standards-v8.38.3","actor":{"login":"github-actions[bot]"},"triggering_actor":{"login":"github-actions[bot]"},"run_attempt":1}\n' ;;
      */actions/runs/10) printf '{"event":"workflow_dispatch","head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","head_branch":"standards-v8.38.3","actor":{"login":"github-actions[bot]"},"triggering_actor":{"login":"human"},"run_attempt":2}\n' ;;
      */actions/runs/11) printf '{"event":"workflow_dispatch","head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","head_branch":"main","actor":{"login":"github-actions[bot]"},"triggering_actor":{"login":"github-actions[bot]"},"run_attempt":1}\n' ;;
      *"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...$PUBLISHED_SHA") printf 'ahead\n' ;;
      *"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb...$PUBLISHED_SHA") printf 'behind\n' ;;
      *"cccccccccccccccccccccccccccccccccccccccc...$PUBLISHED_SHA") printf 'diverged\n' ;;
      *) return 23 ;;
    esac
  elif [[ "$1 $2" == 'run cancel' ]]; then
    printf 'cancel %s\n' "$3" >> "$EVENTS"
    [[ "$FAILURE" != cancel ]] || return 21
  elif [[ "$1 $2" == 'workflow run' ]]; then
    printf 'dispatch\n' >> "$EVENTS"
  else
    return 29
  fi
}
"""
    jq = shutil.which("jq")
    assert jq is not None
    environment = {
        "PATH": f"{Path(jq).parent}{os.pathsep}{os.defpath}",
        "GITHUB_REPOSITORY": "example/standards",
        "RUNS": str(runs),
        "EVENTS": str(events),
        "FAILURE": failure,
    }

    environment.update(_dispatch_step_environment(published))

    result = subprocess.run(
        ("bash", "-c", stub + _release_dispatch_command()),
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    expected = (
        ["dispatch"]
        if failure in {"list", "compare", "published"}
        else ["cancel 1", "cancel 8", "cancel 9", "dispatch"]
    )
    assert events.read_text(encoding="utf-8").splitlines() == expected
    concurrency = _workflow()["concurrency"]
    assert _is_object(concurrency)
    assert concurrency["cancel-in-progress"] == "false"


def _release_dispatch_command() -> str:
    return (REPO_ROOT / ".github/scripts/dispatch-standards-rollout.sh").read_text(encoding="utf-8")


def _dispatch_step_environment(published: str) -> dict[str, str]:
    workflow = _load_yaml(REPO_ROOT / ".github/workflows/release-tags.yml")
    assert _is_object(workflow)
    jobs = workflow["jobs"]
    assert _is_object(jobs)
    dispatch = jobs["dispatch-rollout"]
    assert _is_object(dispatch)
    steps = dispatch["steps"]
    assert _is_array(steps)
    step = steps[-1]
    assert _is_object(step)
    step_environment = step["env"]
    assert _is_object(step_environment)
    context = {
        "${{ github.token }}": "fixture-token",
        "${{ needs.preflight.outputs.standards_tag }}": "standards-v8.38.4",
        "${{ github.event.workflow_run.head_sha }}": published,
    }
    environment: dict[str, str] = {}
    for name, expression in step_environment.items():
        assert isinstance(expression, str)
        environment[name] = context[expression]
    return environment


@dataclass(frozen=True)
class _RolloutRecorder:
    environment: dict[str, str]
    commands: Path


def _rollout_recorder(tmp_path: Path, **values: str) -> _RolloutRecorder:
    commands = tmp_path / "commands.jsonl"
    binary = tmp_path / "bin"
    binary.mkdir()
    runner = binary / "runner"
    runner.write_text(
        f"#!{sys.executable}\n"
        r"""
import json
import os
from pathlib import Path
import sys
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with Path(os.environ["RECORDS"]).open("a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
if name == "uvx":
    print("code-standards " + os.environ.get("PUBLISHED_VERSION", "8.39.0"))
elif name == "uv":
    if "--github-output" in args:
        Path(args[args.index("--github-output") + 1]).write_text(os.environ.get("MATRIX_OUTPUT", "consumers=[]\n"))
    print("controller output")
    sys.exit(int(os.environ.get("UV_STATUS", "0")))
elif name == "gh" and args[:2] == ["issue", "list"]:
    print(os.environ.get("ISSUES", "[]"))
elif name == "curl":
    Path(args[args.index("--output") + 1]).write_text("fixture bootstrap\n")
elif name == "sha256sum":
    from hashlib import sha256
    expected, path = sys.stdin.read().strip().split(None, 1)
    sys.exit(0 if sha256(Path(path).read_bytes()).hexdigest() == expected else 1)
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    for name in ("uv", "uvx", "git", "gh", "curl", "sha256sum"):
        (binary / name).symlink_to(runner)
    output = tmp_path / "outputs"
    output.touch()
    summary = tmp_path / "summary"
    summary.touch()
    inherited = credential_free_environment()
    environment = {
        **inherited,
        "PATH": f"{binary}{os.pathsep}{inherited['PATH']}",
        "RECORDS": str(commands),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_REPOSITORY": "example/standards",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_RUN_ID": "123",
        "GH_TOKEN": "fixture-token",
        "REGISTRY_TOML": "fixture registry\n",
        "VERSION": "8.39.0",
        **values,
    }
    return _RolloutRecorder(environment=environment, commands=commands)


def _run_rollout(script: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("bash", str(REPO_ROOT / ".github/scripts" / script)),
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


class _RecordedCommand(RootModel[list[str]]):
    pass


def _recorded_commands(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [_RecordedCommand.model_validate_json(line).root for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("requested", "event", "expected", "status"),
    [
        ("8.39.0", "workflow_dispatch", "8.39.0", 0),
        ("", "schedule", "8.39.0", 0),
        ("", "workflow_dispatch", "", 2),
        ("bad; command", "workflow_dispatch", "", 2),
    ],
)
def test_rollout_version_executes_only_the_schedule_lookup(
    tmp_path: Path, requested: str, event: str, expected: str, status: int
) -> None:
    recorder = _rollout_recorder(tmp_path, REQUESTED_VERSION=requested, EVENT_NAME=event)
    environment = recorder.environment
    commands = recorder.commands
    result = _run_rollout("rollout-version.sh", environment)
    assert result.returncode == status
    assert Path(environment["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == (
        f"version={expected}\n" if expected else ""
    )
    assert _recorded_commands(commands) == (
        [
            [
                "uvx",
                "--no-config",
                "--isolated",
                "--python",
                "3.14",
                "--refresh",
                "--from",
                "code-standards",
                "code-standards",
                "--version",
            ]
        ]
        if event == "schedule"
        else []
    )


@pytest.mark.parametrize("controller_status", [0, 17])
def test_rollout_plan_preserves_controller_status_matrix_and_private_registry(
    tmp_path: Path, controller_status: int
) -> None:
    recorder = _rollout_recorder(
        tmp_path, UV_STATUS=str(controller_status), MATRIX_OUTPUT='consumers=[{"identity":"example/app"}]\n'
    )
    environment = recorder.environment
    commands = recorder.commands
    result = _run_rollout("rollout-plan.sh", environment)
    assert result.returncode == 0
    output = Path(environment["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
    assert (
        output
        == f"plan_status={controller_status}\nconsumers="
        + ('[{"identity":"example/app"}]' if controller_status == 0 else "[]")
        + "\n"
    )
    registry = tmp_path / "standards-rollout.toml"
    assert registry.read_text(encoding="utf-8") == environment["REGISTRY_TOML"]
    assert registry.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "standards-rollout.log").read_text(encoding="utf-8") == "controller output\n"
    assert _recorded_commands(commands) == [
        [
            "uv",
            "run",
            "--project",
            "packages/standards",
            "--frozen",
            "python",
            "-m",
            "sarj_standards.libs.release.rollout",
            "--registry",
            str(registry),
            "--jobs",
            "4",
            "--github-output",
            str(tmp_path / "rollout-plan.outputs"),
            "plan",
            "--version",
            environment["VERSION"],
        ]
    ]


@pytest.mark.parametrize("missing", ["GH_TOKEN", "REGISTRY_TOML"])
def test_rollout_plan_records_missing_configuration_without_invoking_controller(tmp_path: Path, missing: str) -> None:
    recorder = _rollout_recorder(tmp_path, **{missing: ""})
    environment = recorder.environment
    commands = recorder.commands
    assert _run_rollout("rollout-plan.sh", environment).returncode == 0
    assert Path(environment["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == "plan_status=1\nconsumers=[]\n"
    assert _recorded_commands(commands) == []


@pytest.mark.parametrize(("event", "operation"), [("schedule", "reconcile"), ("workflow_dispatch", "apply")])
@pytest.mark.parametrize("controller_status", [0, 19])
def test_rollout_apply_uses_exact_consumer_and_preserves_failure(
    tmp_path: Path, event: str, operation: str, controller_status: int
) -> None:
    consumer = "example/app"
    recorder = _rollout_recorder(tmp_path, EVENT_NAME=event, CONSUMER=consumer, UV_STATUS=str(controller_status))
    environment = recorder.environment
    commands = recorder.commands
    assert _run_rollout("rollout-apply.sh", environment).returncode == controller_status
    assert (tmp_path / "standards-rollout.status").read_text(encoding="utf-8") == f"{controller_status}\n"
    recorded = _recorded_commands(commands)
    assert recorded[:3] == [
        ["gh", "auth", "setup-git"],
        ["git", "config", "--global", "user.name", "sarj-standards-rollout[bot]"],
        ["git", "config", "--global", "user.email", "sarj-standards-rollout[bot]@users.noreply.github.com"],
    ]
    assert recorded[3] == [
        "uv",
        "run",
        "--project",
        "packages/standards",
        "--frozen",
        "python",
        "-m",
        "sarj_standards.libs.release.rollout",
        "--registry",
        str(tmp_path / "standards-rollout.toml"),
        operation,
        "--version",
        environment["VERSION"],
        "--consumer",
        consumer,
    ]


@pytest.mark.parametrize(
    ("plan_status", "leg_status", "rollout_result", "fleet_status", "expected"),
    [
        (0, 0, "success", 0, "success"),
        (0, 0, "success", 1, "pending"),
        (0, 0, "failure", 0, "failure"),
        (0, 17, "success", 0, "failure"),
        (2, 0, "skipped", 0, "failure"),
        (0, 0, "success", 2, "failure"),
    ],
)
def test_rollout_report_combines_real_artifacts_and_controller_status(
    tmp_path: Path, *, plan_status: int, leg_status: int, rollout_result: str, fleet_status: int, expected: str
) -> None:
    recorder = _rollout_recorder(
        tmp_path,
        PLAN_STATUS=str(plan_status),
        CONSUMERS='[{"identity":"example/app"}]',
        ROLLOUT_RESULT=rollout_result,
        UV_STATUS=str(fleet_status),
    )
    environment = recorder.environment
    commands = recorder.commands
    directory = tmp_path / "rollout-logs" / "standards-rollout-log-consumer-0"
    directory.mkdir(parents=True)
    (directory / "standards-rollout.log").write_text("consumer output\n")
    (directory / "standards-rollout.status").write_text(f"{leg_status}\n")
    assert _run_rollout("rollout-report.sh", environment).returncode == 0
    assert (
        Path(environment["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
        == f"result={expected}\noperation_status={max(plan_status, leg_status, int(rollout_result != 'success'))}\nstatus_status={fleet_status}\n"
    )
    assert (tmp_path / "standards-rollout.log").read_text(encoding="utf-8") == "consumer output\ncontroller output\n"
    assert _recorded_commands(commands) == [
        [
            "uv",
            "run",
            "--project",
            "packages/standards",
            "--frozen",
            "python",
            "-m",
            "sarj_standards.libs.release.rollout",
            "--registry",
            str(tmp_path / "standards-rollout.toml"),
            "--jobs",
            "4",
            "status",
            "--version",
            environment["VERSION"],
        ]
    ]


@pytest.mark.parametrize(
    ("result", "issue_state", "expected_operations"),
    [
        ("success", "OPEN", ["edit", "comment", "close"]),
        ("failure", "CLOSED", ["edit", "reopen"]),
        ("pending", "", ["create"]),
        ("success", "", []),
    ],
)
def test_rollout_publish_status_executes_durable_issue_transitions(
    tmp_path: Path, result: str, issue_state: str, expected_operations: list[str]
) -> None:
    issues = [{"number": 42, "title": "[Standards rollout] 8.39.0", "state": issue_state}] if issue_state else []
    recorder = _rollout_recorder(
        tmp_path, RESULT=result, OPERATION_STATUS="0", STATUS_STATUS="0", ISSUES=json.dumps(issues)
    )
    environment = recorder.environment
    commands = recorder.commands
    (tmp_path / "standards-rollout.log").write_text("recorded controller output\n")
    assert _run_rollout("rollout-publish-status.sh", environment).returncode == 0
    recorded = _recorded_commands(commands)
    assert recorded[0] == [
        "gh",
        "issue",
        "list",
        "--repo",
        environment["GITHUB_REPOSITORY"],
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "number,title,state",
    ]
    assert [command[2] for command in recorded[1:]] == expected_operations
    body = (tmp_path / "standards-rollout-issue.md").read_text(encoding="utf-8")
    assert "recorded controller output" in body
    assert Path(environment["GITHUB_STEP_SUMMARY"]).read_text(encoding="utf-8") == body
    for command in recorded[1:]:
        assert command[command.index("--repo") + 1] == environment["GITHUB_REPOSITORY"]
        if command[2] in {"edit", "create"}:
            assert command[command.index("--body-file") + 1] == str(tmp_path / "standards-rollout-issue.md")


@pytest.mark.parametrize("checksum_matches", [True, False])
def test_rollout_bootstrap_verifies_download_before_exposing_executable(
    tmp_path: Path, *, checksum_matches: bool
) -> None:
    github_path = tmp_path / "github-path"
    github_path.touch()
    digest = sha256(b"fixture bootstrap\n").hexdigest() if checksum_matches else "0" * 64
    recorder = _rollout_recorder(tmp_path, MISE_VERSION="2026.8.8", MISE_SHA256=digest, GITHUB_PATH=str(github_path))
    environment = recorder.environment
    commands = recorder.commands
    result = _run_rollout("rollout-bootstrap.sh", environment)
    assert (result.returncode == 0) == checksum_matches
    assert github_path.read_text(encoding="utf-8") == (f"{tmp_path / 'mise-bin'}\n" if checksum_matches else "")
    assert _recorded_commands(commands) == [
        [
            "curl",
            "--fail",
            "--location",
            "--retry",
            "3",
            "--silent",
            "--show-error",
            "https://github.com/jdx/mise/releases/download/v2026.8.8/mise-v2026.8.8-linux-x64",
            "--output",
            str(tmp_path / "mise-bin/mise"),
        ],
        ["sha256sum", "--check", "--strict"],
    ]
    if checksum_matches:
        assert (tmp_path / "mise-bin/mise").stat().st_mode & 0o777 == 0o755


def test_rollout_report_rejects_invalid_consumer_json_before_querying_controller(tmp_path: Path) -> None:
    recorder = _rollout_recorder(tmp_path, PLAN_STATUS="0", CONSUMERS="invalid JSON", ROLLOUT_RESULT="success")
    environment = recorder.environment
    commands = recorder.commands
    result = _run_rollout("rollout-report.sh", environment)
    assert result.returncode != 0
    assert not Path(environment["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
    assert _recorded_commands(commands) == []
