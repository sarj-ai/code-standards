from __future__ import annotations

import base64
import json
import subprocess
import sys
from threading import Barrier, Lock
import time
from typing import TYPE_CHECKING, final

import pytest

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


VERSION = "8.32.0"
FLEET = (
    rollout.Consumer("Canary", "example/canary", "main", ("true",), channel=rollout.RolloutChannel.CANARY),
    rollout.Consumer("Early", "example/early", "main", ("true",), channel=rollout.RolloutChannel.EARLY),
    rollout.Consumer("Stable", "example/stable", "main", ("true",)),
)


def fleet_registry(tmp_path: Path) -> Path:
    path = tmp_path / "fleet.toml"
    entries = ["schema = 1"]
    entries.extend(
        f'[[consumer]]\nname = "{item.name}"\nrepository = "{item.repository}"\n'
        f'branch = "{item.branch}"\nchannel = "{item.channel}"\nverify = ["true"]'
        for item in FLEET
    )
    path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return path


@final
class FleetRunner:
    def __init__(
        self, adopted: frozenset[str] = frozenset(), *, failed: str = "", barrier: Barrier | None = None
    ) -> None:
        self.adopted = adopted
        self.failed = failed
        self.barrier = barrier
        self.commands: list[tuple[str, ...]] = []
        self.lock = Lock()

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd is None
        assert env is None
        with self.lock:
            self.commands.append(tuple(command))
        if command[0] == "uvx":
            output = f"code-standards {VERSION}"
        elif tuple(command[:2]) == ("git", "ls-remote"):
            output = f"{'c' * 40}\trefs/tags/standards-v{VERSION}\n{'a' * 40}\trefs/tags/standards-v{VERSION}^{{}}\n"
        elif tuple(command[:3]) == ("gh", "pr", "list"):
            if self.barrier is not None:
                barrier_index = self.barrier.wait(timeout=5)
                assert 0 <= barrier_index < self.barrier.parties
            repository = command[command.index("--repo") + 1]
            if repository == self.failed:
                msg = "temporary GitHub outage"
                raise rollout.RolloutError(msg)
            output = "[]"
        elif tuple(command[:2]) == ("gh", "api"):
            repository = command[2].removeprefix("repos/").removesuffix("/contents/.sarj-standards.toml")
            version = VERSION if repository in self.adopted else "8.31.1"
            source = f'schema = 4\nbundle = "{version}"\n'
            output = json.dumps({"content": base64.b64encode(source.encode()).decode()})
        else:
            pytest.fail(f"unexpected mutation or transport: {command}")
        assert check or tuple(command[:2]) == ("gh", "api") or command[0] == "uvx"
        return subprocess.CompletedProcess(command, 0, output, "")


@pytest.mark.parametrize("selected", [None, FLEET[0].identity], ids=("fleet", "targeted-canary"))
def test_missing_canary_advances_while_later_waves_wait(selected: str | None) -> None:
    runner = FleetRunner()

    outcomes = rollout.apply(VERSION, FLEET, runner, consumer=selected, dry_run=True)

    assert outcomes[0].state is rollout.OutcomeState.WOULD_CREATE
    if selected is None:
        assert [item.state for item in outcomes[1:]] == [rollout.OutcomeState.BLOCKED] * 2
    assert not any(command[:3] == ("gh", "repo", "clone") for command in runner.commands)


def test_early_wave_advances_after_canary_without_waiting_for_stable() -> None:
    runner = FleetRunner(frozenset({FLEET[0].repository}))

    outcomes = rollout.apply(VERSION, FLEET, runner, dry_run=True)

    assert [item.state for item in outcomes] == [
        rollout.OutcomeState.ALREADY_CURRENT,
        rollout.OutcomeState.WOULD_CREATE,
        rollout.OutcomeState.BLOCKED,
    ]
    canary_reads = [
        command for command in runner.commands if "repos/example/canary/contents/.sarj-standards.toml" in command
    ]
    assert len(canary_reads) == 1


def test_targeted_later_wave_keeps_full_fleet_prerequisites() -> None:
    runner = FleetRunner()

    outcomes = rollout.apply(VERSION, FLEET, runner, consumer=FLEET[2].identity, dry_run=True)

    assert len(outcomes) == 1
    assert outcomes[0].state is rollout.OutcomeState.BLOCKED
    assert not any("--head" in command and FLEET[2].repository in command for command in runner.commands)


@pytest.mark.parametrize("command", [rollout.RolloutCommand.PLAN, rollout.RolloutCommand.STATUS])
def test_unknown_consumer_fails_before_release_resolution(command: rollout.RolloutCommand, tmp_path: Path) -> None:
    registry = tmp_path / "fleet.toml"
    registry.write_text(
        'schema = 1\n[[consumer]]\nname = "Only"\nrepository = "example/only"\nbranch = "main"\nverify = ["true"]\n',
        encoding="utf-8",
    )
    runner = FakeRolloutRunner()
    args = rollout.RolloutArgs(registry=registry, command=command, version=VERSION, consumer="example/unknown@main")

    with pytest.raises(rollout.RolloutError, match="consumer"):
        rollout.execute(args, runner)

    assert runner.commands == []


def test_parallel_status_overlaps_requests_and_preserves_registry_order() -> None:
    runner = FleetRunner(frozenset(item.repository for item in FLEET[:2]), barrier=Barrier(2))

    outcomes = rollout.status(VERSION, FLEET[:2], runner, jobs=2)

    assert [item.consumer for item in outcomes] == list(FLEET[:2])
    assert all(item.state is rollout.OutcomeState.ALREADY_CURRENT for item in outcomes)
    assert all(item.elapsed_seconds is not None for item in outcomes)


@pytest.mark.parametrize("jobs", [1, 2], ids=("sequential", "parallel"))
def test_status_failure_does_not_hide_other_consumers(jobs: int) -> None:
    runner = FleetRunner(frozenset({FLEET[1].repository}), failed=FLEET[0].repository)

    outcomes = rollout.status(VERSION, FLEET[:2], runner, jobs=jobs)

    assert [item.state for item in outcomes] == [rollout.OutcomeState.ERROR, rollout.OutcomeState.ALREADY_CURRENT]
    assert "GitHub outage" in outcomes[0].detail


def test_parallel_apply_overlaps_consumers_in_one_wave() -> None:
    consumers = tuple(rollout.Consumer(item.name, item.repository, item.branch, item.verify) for item in FLEET[:2])
    runner = FleetRunner(barrier=Barrier(2))

    outcomes = rollout.apply(VERSION, consumers, runner, dry_run=True, jobs=2)

    assert [item.consumer for item in outcomes] == list(consumers)
    assert all(item.state is rollout.OutcomeState.WOULD_CREATE for item in outcomes)


@pytest.mark.parametrize("jobs", [0, 17])
def test_invalid_concurrency_is_rejected(jobs: int) -> None:
    with pytest.raises(rollout.RolloutError, match="between 1 and 16"):
        rollout.status(VERSION, FLEET, FleetRunner(), jobs=jobs)


def test_command_timeout_is_bounded_and_actionable() -> None:
    runner = rollout.SubprocessRunner(command_timeout=0.05)

    with pytest.raises(rollout.RolloutError, match=r"0\.05s command timeout"):
        runner.run((sys.executable, "-c", "import time; time.sleep(10)"))


@pytest.mark.parametrize("partial_clone", [False, True], ids=("complete-history", "filtered-history"))
def test_blob_filtering_requires_explicit_consumer_opt_in(partial_clone: bool) -> None:
    target = rollout.Consumer("Example", "example/consumer", "main", ("true",), partial_clone=partial_clone)
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")])

    with pytest.raises(rollout.RolloutError, match="cloned base"):
        rollout.apply_one(target, VERSION, runner)

    clone = next(command for command in runner.commands if command[:3] == ("gh", "repo", "clone"))
    assert ("--filter=blob:none" in clone) is partial_clone
    assert "--single-branch" not in clone
    assert "--depth" not in clone


def test_progress_keeps_stdout_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    outcomes = rollout.apply(VERSION, FLEET[:1], FleetRunner(), dry_run=True)
    rollout.print_outcomes(VERSION, outcomes)

    captured = capsys.readouterr()
    payload = parse_json(captured.out)
    assert rollout.is_object(payload)
    assert "checking current adoption" in captured.err
    assert FLEET[0].identity in captured.err
    rows = payload["consumers"]
    assert rollout.is_array(rows)
    assert rollout.is_object(rows[0])
    assert isinstance(rows[0]["elapsedSeconds"], float)


def test_planner_skips_settled_consumers_and_closed_waves() -> None:
    outcomes = (
        rollout.Outcome(FLEET[0], rollout.OutcomeState.PR_OPEN),
        rollout.Outcome(FLEET[1], rollout.OutcomeState.MISSING),
        rollout.Outcome(FLEET[2], rollout.OutcomeState.MISSING),
    )

    assert rollout.pending_matrix(outcomes) == []
    advanced = (rollout.Outcome(FLEET[0], rollout.OutcomeState.ALREADY_CURRENT), *outcomes[1:])
    assert rollout.pending_matrix(advanced) == [{"name": FLEET[1].name, "identity": FLEET[1].identity}]


def test_planner_retries_failed_verification_but_preserves_unowned_prs() -> None:
    failed = rollout.Outcome(
        FLEET[0], rollout.OutcomeState.BLOCKED, detail="consumer verification failed; reconcile will retry"
    )
    unowned = rollout.Outcome(FLEET[0], rollout.OutcomeState.BLOCKED, detail="ownership marker does not match")

    assert rollout.pending_matrix((failed,)) == [{"name": FLEET[0].name, "identity": FLEET[0].identity}]
    assert rollout.pending_matrix((unowned,)) == []


def test_plan_cli_appends_a_valid_pending_matrix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = fleet_registry(tmp_path)
    output = tmp_path / "github-output"
    output.write_text("unrelated=value\n", encoding="utf-8")
    runner = FleetRunner(frozenset({FLEET[0].repository}))

    result = rollout.main(
        [
            "--registry",
            str(registry),
            "--jobs",
            "2",
            "--command-timeout",
            "60",
            "--github-output",
            str(output),
            "plan",
            "--version",
            VERSION,
        ],
        runner=runner,
    )

    assert result == 0
    assert rollout.is_object(parse_json(capsys.readouterr().out))
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "unrelated=value"
    assert parse_json(lines[1].removeprefix("consumers=")) == [{"name": FLEET[1].name, "identity": FLEET[1].identity}]


@pytest.mark.parametrize(("state", "expected"), [("adopted", 0), ("pending", 1), ("failed", 2)])
def test_status_cli_distinguishes_pending_from_failure(
    state: str, expected: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = fleet_registry(tmp_path)
    adopted: frozenset[str] = frozenset({FLEET[0].repository}) if state == "adopted" else frozenset()
    runner = FleetRunner(adopted, failed=FLEET[0].repository if state == "failed" else "")

    result = rollout.main(
        ["--registry", str(registry), "status", "--version", VERSION, "--consumer", FLEET[0].identity], runner=runner
    )

    assert result == expected
    payload = parse_json(capsys.readouterr().out)
    assert rollout.is_object(payload)
    rows = payload["consumers"]
    assert rollout.is_array(rows)
    assert len(rows) == 1
    assert all(FLEET[1].repository not in command for command in runner.commands)


def test_dependency_trees_do_not_expand_managed_paths_or_select_corepack(tmp_path: Path) -> None:
    for directory in ("node_modules/dependency", ".venv/dependency", "apps/web"):
        path = tmp_path / directory
        path.mkdir(parents=True)
        (path / "package.json").write_text('{"packageManager":"yarn@4.0.0"}', encoding="utf-8")
    paths = rollout.managed_rollout_paths(tmp_path, frozenset())

    assert "apps/web/package.json" in paths
    assert "node_modules/dependency/package.json" not in paths
    assert ".venv/dependency/package.json" not in paths
    assert rollout.repository_files(tmp_path, frozenset({"package.json"})) == (tmp_path / "apps/web/package.json",)
    (tmp_path / "apps/web/package.json").write_text("{}", encoding="utf-8")
    assert rollout._declared_corepack_manager(tmp_path) is None  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- regression at the package-manager discovery boundary.


def test_git_metadata_batches_tracking_and_rejects_untracked_executables(tmp_path: Path) -> None:
    executable = tmp_path / "script.sh"
    executable.write_text("echo hello\n", encoding="utf-8")
    executable.chmod(0o755)
    runner = FakeRolloutRunner([(0, ""), (0, ""), (0, "tracked.toml\0")])

    with pytest.raises(rollout.RolloutError, match="executable"):
        rollout.reject_git_metadata(tmp_path, ("tracked.toml", "script.sh"), runner)

    assert runner.commands[-1] == ("git", "ls-files", "-z", "--", "tracked.toml", "script.sh")
    assert len(runner.commands) == 3


@pytest.mark.parametrize("failed", [False, True])
def test_progress_reports_phase_and_total_time_even_when_a_phase_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failed: bool
) -> None:
    values = iter((10.0, 10.0, 12.5, 16.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(values))  # sarj-noqa: SARJ445 -- deterministic phase clock
    target = rollout.Consumer("Example", "example/consumer", "main", ("true",))

    def fail() -> None:
        msg = "failure"
        raise ValueError(msg)

    try:
        with rollout.timed_progress(target) as report:
            report("baseline")
            report("verification")
            if failed:
                fail()
    except ValueError:
        assert failed
    output = capsys.readouterr().err
    assert "finished baseline in 2.50s" in output
    assert "ended verification after 3.50s; total 6.00s" in output


@pytest.mark.parametrize("failed", ["", "uv", "npm"])
def test_bootstrap_overlaps_locked_environments_but_waits_before_custom_commands(tmp_path: Path, failed: str) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/uv.lock").write_text("version = 1\n")
    (tmp_path / "primary").mkdir()
    (tmp_path / "secondary").mkdir()
    (tmp_path / "secondary/package-lock.json").write_text("{}\n")
    (tmp_path / ".sarj-standards.toml").write_text(
        'schema = 4\nbundle = "8.32.0"\n[dest]\npython = "backend"\ntypescript = "primary"\n'
        '[ci]\nbootstrap = ["generate", "typegen"]\n'
    )
    ready = Barrier(2, timeout=5)
    finished: set[str] = set()
    lock = Lock()
    bootstrap: list[str] = []

    @final
    class Runner:
        def run(
            self,
            command: Sequence[str],
            *,
            cwd: Path | None = None,
            check: bool = True,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            assert cwd is not None
            assert not check
            assert env == {"PATH": "/tools"}
            tool = command[0]
            if tool in {"uv", "npm"}:
                ready.wait()
                with lock:
                    finished.add(tool)
                code = 7 if tool == failed else 0
                return subprocess.CompletedProcess(command, code, tool, "")
            assert finished == {"uv", "npm"}
            bootstrap.append(command[-1])
            return subprocess.CompletedProcess(command, 0, "", "")

    result = rollout.run_consumer_bootstrap(tmp_path, (), Runner(), {"PATH": "/tools"})
    assert finished == {"uv", "npm"}
    assert bootstrap == ([] if failed else ["generate", "typegen"])
    assert (result is None) is (not failed)


@pytest.mark.parametrize("single_branch", [False, True])
def test_reduced_clone_scope_requires_registry_opt_in(single_branch: bool, tmp_path: Path) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(
        'schema = 1\n[[consumer]]\nname = "Example"\nrepository = "example/consumer"\n'
        'branch = "main"\nverify = ["true"]\n' + f"single_branch = {str(single_branch).lower()}\n"
    )
    target = rollout.load_registry(path)[0]
    runner = FakeRolloutRunner([(0, "[]"), (1, "HTTP 404")])
    with pytest.raises(rollout.RolloutError, match="cloned base"):
        rollout.apply_one(target, VERSION, runner)
    command = next(command for command in runner.commands if command[:3] == ("gh", "repo", "clone"))
    assert ("--single-branch" in command) is single_branch
    assert ("--no-tags" in command) is single_branch
    assert "--depth" not in command
