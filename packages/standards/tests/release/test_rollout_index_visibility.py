from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


VERSION = "8.38.2"
TOOL = (
    "uvx",
    "--isolated",
    "--python",
    "3.14",
    "--from",
    f"code-standards=={VERSION}",
    "code-standards",
    "--root",
    ".",
)
NOT_VISIBLE = (
    "error: No solution found when resolving tool dependencies\n"
    f"  cause: Because there is no version of code-standards=={VERSION} and you require code-standards=={VERSION}"
)


def test_consumer_install_refreshes_its_provisioned_uv_and_reuses_successful_resolution() -> None:
    runner = FakeRolloutRunner(
        [(1, NOT_VISIBLE), (0, f"code-standards {VERSION}"), (0, "updated")], probe_consumer_release=False
    )
    sleeps: list[float] = []
    environment = {"PATH": "/isolated/consumer-uv"}
    repo = Path("consumer")

    rollout.update_consumer_bundle(
        repo, VERSION, runner, ("mise", "exec", "--"), TOOL, environment=environment, sleep=sleeps.append
    )

    assert len(runner.commands) == 3
    assert runner.commands[0] == runner.commands[1]
    assert "--refresh" not in runner.commands[2]
    command = runner.commands[0]
    assert command[:5] == ("mise", "exec", "--", "uvx", "--refresh")
    assert command[-1] == "--version"
    assert runner.commands[2][-3:] == ("update", "--to", VERSION)
    assert runner.environments == [environment] * 3
    assert runner.working_directories == [repo] * 3
    assert sleeps == [rollout.RELEASE_VISIBILITY_DELAY.total_seconds()]


def test_visible_release_installs_without_waiting() -> None:
    runner = FakeRolloutRunner([(0, f"code-standards {VERSION}"), (0, "updated")], probe_consumer_release=False)
    sleeps: list[float] = []

    rollout.update_consumer_bundle(Path("consumer"), VERSION, runner, (), TOOL, environment={}, sleep=sleeps.append)

    assert len(runner.commands) == 2
    assert not sleeps


def test_missing_consumer_release_stops_at_the_visibility_deadline() -> None:
    runner = FakeRolloutRunner([(1, NOT_VISIBLE)] * rollout.RELEASE_VISIBILITY_ATTEMPTS, probe_consumer_release=False)
    sleeps: list[float] = []

    with pytest.raises(subprocess.CalledProcessError, match="non-zero exit status") as raised:
        rollout.update_consumer_bundle(Path("consumer"), VERSION, runner, (), TOOL, environment={}, sleep=sleeps.append)

    assert raised.value.returncode == 1
    assert len(runner.commands) == rollout.RELEASE_VISIBILITY_ATTEMPTS
    assert sum(sleeps) == 60


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param("update failed after writing configuration", id="update-mutation"),
        pytest.param(NOT_VISIBLE.replace("tool dependencies", "project dependencies"), id="consumer-resolution"),
        pytest.param(NOT_VISIBLE.replace(VERSION, VERSION + "0"), id="different-exact-version"),
        pytest.param(NOT_VISIBLE.replace("code-standards==", "repo-standards=="), id="different-package"),
        pytest.param("No solution found when resolving tool dependencies: conflicting transitive pins", id="conflict"),
    ],
)
def test_unrelated_install_failures_do_not_repeat_consumer_updates(failure: str) -> None:
    runner = FakeRolloutRunner([(1, failure), (0, "must not run")], probe_consumer_release=False)
    sleeps: list[float] = []

    with pytest.raises(subprocess.CalledProcessError) as raised:
        rollout.update_consumer_bundle(Path("consumer"), VERSION, runner, (), TOOL, environment={}, sleep=sleeps.append)

    assert raised.value.returncode == 1
    assert len(runner.commands) == 1
    assert not sleeps


def test_update_failure_after_a_successful_probe_never_repeats_mutations() -> None:
    runner = FakeRolloutRunner([(0, f"code-standards {VERSION}"), (1, NOT_VISIBLE)], probe_consumer_release=False)
    sleeps: list[float] = []

    with pytest.raises(subprocess.CalledProcessError):
        rollout.update_consumer_bundle(Path("consumer"), VERSION, runner, (), TOOL, environment={}, sleep=sleeps.append)

    assert len(runner.commands) == 2
    assert sum("update" in command for command in runner.commands) == 1
    assert not sleeps


def test_wrong_reported_version_stops_before_update() -> None:
    runner = FakeRolloutRunner([(0, "code-standards 8.38.1")], probe_consumer_release=False)

    with pytest.raises(rollout.RolloutError, match="consumer package probe did not report"):
        rollout.update_consumer_bundle(Path("consumer"), VERSION, runner, (), TOOL, environment={})

    assert len(runner.commands) == 1
    assert not any("update" in command for command in runner.commands)
