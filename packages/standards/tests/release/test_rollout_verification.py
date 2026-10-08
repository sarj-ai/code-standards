from __future__ import annotations

from dataclasses import replace
import json
import subprocess
from threading import Barrier
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


@pytest.mark.parametrize("failed", ["", "prepare", "lint", "tests"])
@pytest.mark.parametrize("jobs", [1, 2])
def test_preparation_finishes_before_checks_and_each_failure_blocks(tmp_path: Path, failed: str, jobs: int) -> None:
    both_started = Barrier(2) if jobs == 2 else None
    calls: list[str] = []
    completed: list[str] = []

    class Runner:
        def run(
            self,
            command: Sequence[str],
            *,
            cwd: Path | None = None,
            check: bool = True,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            assert cwd == tmp_path
            assert not check
            assert env == {"SARJ_STANDARDS_BASE": "a" * 40}
            assert command[0] == "prefix"
            label = command[1]
            calls.append(label)
            if label != "prepare":
                assert "prepare" in completed
                if both_started is not None:
                    both_started.wait(timeout=5)
            completed.append(label)
            return subprocess.CompletedProcess(command, int(label == failed), f"{label} output", "")

    consumer = replace(
        rollout.Consumer("Example", "example/consumer", "main", ("prepare",)),
        verify_checks=(("lint",), ("tests",)),
        verify_jobs=jobs,
    )
    result = rollout.run_consumer_verification(
        consumer,
        tmp_path,
        Runner(),
        ("prefix",),
        environment={"SARJ_STANDARDS_BASE": "a" * 40},
    )
    assert bool(result.returncode) == bool(failed)
    assert calls[0] == "prepare"
    assert sorted(completed) == (["prepare"] if failed == "prepare" else ["lint", "prepare", "tests"])
    if failed in {"lint", "tests"}:
        assert f"{failed} output" in result.stdout


def test_existing_registry_command_runs_once_without_extra_checks(tmp_path: Path) -> None:
    class Runner:
        def run(
            self,
            command: Sequence[str],
            *,
            cwd: Path | None = None,
            check: bool = True,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            assert command == ("make", "check")
            assert cwd == tmp_path
            assert not check
            assert env == {}
            return subprocess.CompletedProcess(command, 0, "original output", "")

    result = rollout.run_consumer_verification(
        rollout.Consumer("Example", "example/consumer", "main", ("make", "check")),
        tmp_path,
        Runner(),
        (),
        environment={},
    )
    assert result.stdout == "original output"


@pytest.mark.parametrize("value", [True, 0, 3, 8, "2"])
def test_invalid_verification_worker_budget_is_rejected(tmp_path: Path, value: object) -> None:
    with pytest.raises(rollout.RolloutError, match="verify_jobs"):
        _consumer(
            tmp_path,
            {
                "name": "Example",
                "repository": "example/consumer",
                "branch": "main",
                "verify": ["true"],
                "verify_jobs": value,
            },
        )


@pytest.mark.parametrize(
    "value",
    ["true", ["true"], [[]], [[1]], [[""]], [["true"]] * 17],
    ids=("scalar", "flat", "empty", "number", "blank", "too-many"),
)
def test_invalid_independent_commands_are_rejected(tmp_path: Path, value: object) -> None:
    with pytest.raises(rollout.RolloutError, match="verify_checks"):
        _consumer(
            tmp_path,
            {
                "name": "Example",
                "repository": "example/consumer",
                "branch": "main",
                "verify": ["true"],
                "verify_checks": value,
            },
        )


def test_registry_preserves_argv_and_serial_debugging(tmp_path: Path) -> None:
    consumer = _consumer(
        tmp_path,
        {
            "name": "Example",
            "repository": "example/consumer",
            "branch": "main",
            "verify": ["prepare"],
            "verify_checks": [["lint", "path with spaces"], ["test"]],
            "verify_jobs": 1,
        },
    )
    assert consumer.verify_checks == (("lint", "path with spaces"), ("test",))
    assert consumer.verify_jobs == 1


def _consumer(root: Path, entry: dict[str, object]) -> rollout.Consumer:
    path = root / "registry.toml"
    path.write_text(
        "schema = 1\n[[consumer]]\n" + "\n".join(f"{key} = {json.dumps(value)}" for key, value in entry.items()) + "\n"
    )
    return rollout.load_registry(path)[0]
