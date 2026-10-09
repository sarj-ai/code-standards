from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import TYPE_CHECKING, override

import pytest

from sarj_standards.libs.release import rollout
from sarj_standards.libs.release.verification_process import BaseWatch


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


pytestmark = pytest.mark.skipif(os.name != "posix", reason="verification process groups require POSIX")


@pytest.mark.parametrize("available", [True, False])
def test_stable_or_unavailable_base_runs_preparation_and_every_check(tmp_path: Path, available: bool) -> None:
    def command(name: str, code: int = 0) -> tuple[str, ...]:
        return (
            sys.executable,
            "-c",
            (
                f"import os,time; from pathlib import Path; assert 'GH_TOKEN' not in os.environ; "
                f"Path({str(tmp_path / name)!r}).touch(); time.sleep(.08); print({name!r}); raise SystemExit({code})"
            ),
        )

    consumer = replace(
        rollout.Consumer("Example", "example/consumer", "main", command("prepare")),
        verify_checks=(command("backend"), command("iac failed", 3)),
        verify_jobs=2,
    )
    reads: list[str] = []

    def read_base() -> str | None:
        reads.append("read")
        return "a" * 40 if available else None

    with BaseWatch("a" * 40, read_base, 2, poll_interval=0.01) as runner:
        result = rollout.run_consumer_verification(consumer, tmp_path, runner, (), environment={})
    assert reads
    assert runner.moved_to is None
    assert result.returncode == 1
    assert "iac failed" in result.stdout
    assert all((tmp_path / name).is_file() for name in ("prepare", "backend", "iac failed"))


def test_base_move_stops_owned_child_and_preserves_unrelated_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    ready = tmp_path / "ready"
    script = (
        "import signal,subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "signal.signal(signal.SIGTERM,lambda *_:sys.exit(child.wait())); "
        f"Path({str(pid_file)!r}).write_text(str(child.pid)); "
        f"Path({str(ready)!r}).touch(); print('candidate started',flush=True); time.sleep(30)"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with BaseWatch("a" * 40, lambda: "b" * 40 if ready.exists() else "a" * 40, 5, poll_interval=0.02) as runner:
            result = runner.run((sys.executable, "-c", script), check=False, env={})
        assert result.returncode == 125
        assert runner.moved_to == "b" * 40
        assert "candidate started" in result.stdout
        assert "verification cancelled" in result.stderr
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_stale_candidate_exits_before_amending_or_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = tmp_path / "ready"
    finished = tmp_path / "finished"
    repo = tmp_path / "repo"
    repo.mkdir()
    script = (
        f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); "
        f"print('verification reached',flush=True); time.sleep(10); Path({str(finished)!r}).touch()"
    )
    consumer = rollout.Consumer("Example", "example/consumer", "main", (sys.executable, "-c", script))

    def read_base(_consumer: rollout.Consumer, _runner: rollout.CommandRunner) -> str:
        return "b" * 40 if ready.exists() else "a" * 40

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- supplies deterministic remote ref evidence while real verification subprocesses run.
        rollout, "live_consumer_base_sha", read_base
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- shortens the polling cadence without replacing process termination or verification.
        rollout, "BASE_WATCH_POLL_SECONDS", 0.02
    )
    with pytest.raises(rollout.ConsumerBaseMovedError, match="cancelled stale verification") as caught:
        rollout._verify_rollout_patch(  # pyright: ignore[reportPrivateUsage] # ruff: ignore[private-member-access] -- exercises the complete transaction phase to prove cancellation precedes amendment.
            consumer,
            repo,
            rollout.SubprocessRunner(command_timeout=5),
            "8.38.13",
            (),
            environment={},
            base_sha="a" * 40,
            baseline_path=None,
            expected_baseline=None,
            consumer_baselines={},
            allowed_workflow_paths=frozenset(),
            allowed_baseline_paths=frozenset(),
            allowed_paths=frozenset(),
        )
    # The empty directory is intentionally not a Git checkout: any attempt to
    # amend or push the stale candidate would fail this end-to-end guard test.
    assert "verification reached" in str(caught.value)
    assert not finished.exists()
    assert list(repo.iterdir()) == []


def test_full_transaction_cancels_dependency_update_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = tmp_path / "update-started"
    finished = tmp_path / "update-finished"
    executable = tmp_path / "uvx"
    executable.write_text(
        f"#!{sys.executable}\nimport sys,time\nfrom pathlib import Path\n"
        "if sys.argv[-1] == '--version':\n    print('code-standards 8.38.15')\n"
        "else:\n"
        f"    Path({str(ready)!r}).touch()\n"
        "    print('dependency update started',flush=True)\n    time.sleep(10)\n"
        f"    Path({str(finished)!r}).touch()\n"
    )
    executable.chmod(0o755)
    calls: list[tuple[str, ...]] = []
    consumer = rollout.Consumer("Example", "example/consumer", "main", ("true",))

    class LocalRunner(rollout.SubprocessRunner):
        @override
        def run(
            self,
            command: Sequence[str],
            *,
            cwd: Path | None = None,
            check: bool = True,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(tuple(command))
            if tuple(command[:3]) == ("gh", "repo", "clone"):
                Path(command[4]).mkdir()
                return subprocess.CompletedProcess(command, 0, "", "")
            if tuple(command) == ("git", "rev-parse", "HEAD"):
                return subprocess.CompletedProcess(command, 0, "a" * 40, "")
            return super().run(command, cwd=cwd, check=check, env=env)

    def missing_status(*_args: object) -> rollout.Outcome:
        return rollout.Outcome(consumer, rollout.OutcomeState.MISSING)

    def fresh_branch(*_args: object) -> rollout.BranchPreparation:
        return rollout.BranchPreparation("standards-rollout/current", None)

    def provisioned_tools(*_args: object) -> rollout.ProvisionedTools:
        return rollout.ProvisionedTools({"PATH": str(tmp_path)}, ())

    def read_base(_consumer: rollout.Consumer, _runner: rollout.CommandRunner) -> str:
        return "b" * 40 if ready.exists() else "a" * 40

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- deterministic remote status; the actual update and cancellation run as subprocesses.
        rollout, "status_one", missing_status
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- branch preparation is outside the consumer process boundary under test.
        rollout, "prepare_branch", fresh_branch
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- avoids remote tool installations while the actual uvx argv invokes a local test executable.
        rollout, "provision_consumer_tools", provisioned_tools
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- supplies confirmed remote movement after dependency installation starts.
        rollout, "live_consumer_base_sha", read_base
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- accelerates only the polling interval.
        rollout, "BASE_WATCH_POLL_SECONDS", 0.01
    )
    with pytest.raises(rollout.ConsumerBaseMovedError, match="cancelled stale preparation") as caught:
        rollout.apply_one(consumer, "8.38.15", LocalRunner(5))
    assert "dependency update started" in str(caught.value)
    assert not finished.exists()
    assert not any(command[:2] in {("git", "add"), ("git", "push"), ("gh", "pr")} for command in calls)


def test_timeout_escalates_owned_group_and_retains_partial_output() -> None:
    script = (
        "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "os.write(1,b'x'*10000+b'last output'); os.write(2,b'last error\\xe2\\x82'); time.sleep(30)"
    )
    started = time.monotonic()
    with BaseWatch("a" * 40, lambda: None, 0.5, poll_interval=0.02) as runner:
        result = runner.run((sys.executable, "-c", script), check=False)
    assert 2 <= time.monotonic() - started < 5
    assert result.returncode == 124
    assert len(result.stdout) <= 4000
    assert "last output" in result.stdout
    assert "last error\ufffd" in result.stderr
    assert "0.5s command timeout" in result.stderr


@pytest.mark.parametrize("available", [True, False])
def test_preparation_completes_on_stable_or_unavailable_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    def read_base(_consumer: rollout.Consumer, _runner: rollout.CommandRunner) -> str | None:
        return "a" * 40 if available else None

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- supplies remote evidence while actual preparation subprocesses run.
        rollout, "live_consumer_base_sha", read_base
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- accelerates only the watcher cadence.
        rollout, "BASE_WATCH_POLL_SECONDS", 0.01
    )
    consumer = rollout.Consumer("Example", "example/consumer", "main", ("true",))
    with rollout.consumer_work_runner(consumer, rollout.SubprocessRunner(2), "a" * 40, phase="preparation") as runner:
        result = runner.run((sys.executable, "-c", "import time; time.sleep(.05); print('prepared')"), cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout == "prepared\n"


def test_base_move_cancels_checked_preparation_and_classifies_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = tmp_path / "ready"
    finished = tmp_path / "finished"

    def read_base(_consumer: rollout.Consumer, _runner: rollout.CommandRunner) -> str:
        return "b" * 40 if ready.exists() else "a" * 40

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- deterministic remote movement after the preparation process starts.
        rollout, "live_consumer_base_sha", read_base
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- accelerates only the watcher cadence.
        rollout, "BASE_WATCH_POLL_SECONDS", 0.01
    )
    consumer = rollout.Consumer("Example", "example/consumer", "main", ("true",))

    def prepare(selected: rollout.Consumer) -> rollout.Outcome:
        with rollout.consumer_work_runner(
            selected, rollout.SubprocessRunner(5), "a" * 40, phase="preparation"
        ) as runner:
            runner.run(
                (
                    sys.executable,
                    "-c",
                    (
                        f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); "
                        f"print('partial preparation',flush=True); time.sleep(10); Path({str(finished)!r}).touch()"
                    ),
                ),
                cwd=tmp_path,
            )
        pytest.fail("stale preparation continued to publication")

    result = rollout.consumer_outcome(consumer, prepare)
    assert result.state is rollout.OutcomeState.MISSING
    assert "cancelled stale preparation" in result.detail
    assert "partial preparation" in result.detail
    assert not finished.exists()


def test_initial_base_check_does_not_wait_for_poll_interval() -> None:
    with BaseWatch("a" * 40, lambda: "b" * 40, 2, poll_interval=60) as runner:
        result = runner.run((sys.executable, "-c", "import time; time.sleep(10)"), check=False)
    assert runner.moved_to == "b" * 40
    assert result.returncode == 125
