from __future__ import annotations

from dataclasses import replace
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout
from sarj_standards.libs.release.verification_process import BaseWatch


if TYPE_CHECKING:
    from pathlib import Path


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
