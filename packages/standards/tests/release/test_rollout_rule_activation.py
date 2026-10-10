from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


if TYPE_CHECKING:
    from pathlib import Path


_RULE = "repository/artifacts/makefile-growth"
_VERSION = "8.42.0"
_TOOL = ("uvx", "--from", f"code-standards=={_VERSION}", "code-standards")


@pytest.mark.parametrize(
    "requested", [pytest.param((), id="preserve"), pytest.param((_RULE, "other/rule"), id="opt-in")]
)
def test_bundle_update_forwards_opt_in_to_the_existing_setup_gate(tmp_path: Path, requested: tuple[str, ...]) -> None:
    runner = FakeRolloutRunner()
    environment = {"PATH": "fixture"}

    rollout.update_consumer_bundle(
        tmp_path, _VERSION, runner, (), _TOOL, environment=environment, enable_repository_rules=requested
    )

    assert runner.commands[1] == (*_TOOL, "update", "--to", _VERSION)
    if requested:
        assert runner.commands[2] == (
            *_TOOL,
            "setup",
            "--no-install",
            *(f"--enable-repository-rule={rule_id}" for rule_id in requested),
        )
        assert runner.environments[2] == environment
    else:
        assert len(runner.commands) == 2


def test_declined_setup_activation_stops_the_rollout_update(tmp_path: Path) -> None:
    runner = FakeRolloutRunner([(0, ""), (2, "rule requires an error-stage release")])

    with pytest.raises(subprocess.CalledProcessError, match="exit status 2"):
        rollout.update_consumer_bundle(
            tmp_path, _VERSION, runner, (), _TOOL, environment={}, enable_repository_rules=(_RULE,)
        )


@pytest.mark.parametrize(
    "requested", [pytest.param((), id="preserve"), pytest.param((_RULE, "other/rule"), id="opt-in")]
)
@pytest.mark.parametrize("command", ["plan", "apply"])
def test_cli_collects_repeatable_activation_without_a_default(
    monkeypatch: pytest.MonkeyPatch, command: str, requested: tuple[str, ...]
) -> None:
    captured: list[tuple[str, ...]] = []

    def execute(args: rollout.RolloutArgs, _runner: rollout.CommandRunner) -> int:
        captured.append(args.enable_repository_rules)
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the public dispatch seam records CLI argument parsing before remote operations.
        rollout, "execute", execute
    )
    argv = [command, "--version", _VERSION, *(f"--enable-repository-rule={rule_id}" for rule_id in requested)]

    assert rollout.main(argv, runner=FakeRolloutRunner()) == 0
    assert captured == [requested]


@pytest.mark.parametrize(
    "state", [rollout.OutcomeState.PR_OPEN, rollout.OutcomeState.MERGED, rollout.OutcomeState.ALREADY_CURRENT]
)
def test_requested_activation_cannot_silently_skip_an_existing_rollout(
    monkeypatch: pytest.MonkeyPatch, state: rollout.OutcomeState
) -> None:
    consumer = rollout.Consumer("fixture", "example/fixture", "main", ("true",))

    def status_one(item: rollout.Consumer, _version: str, _runner: rollout.CommandRunner) -> rollout.Outcome:
        return rollout.Outcome(item, state)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- this public status seam supplies an existing rollout without querying GitHub.
        rollout, "status_one", status_one
    )

    with pytest.raises(rollout.RolloutError, match="separate consumer PR"):
        rollout.apply_one(consumer, _VERSION, FakeRolloutRunner(), dry_run=True, enable_repository_rules=(_RULE,))
    assert rollout.apply_one(consumer, _VERSION, FakeRolloutRunner(), dry_run=True).state is state


def test_activation_plan_cannot_filter_out_a_current_consumer_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = rollout.Consumer("fixture", "example/fixture", "main", ("true",))
    current = rollout.Outcome(consumer, rollout.OutcomeState.ALREADY_CURRENT)

    def verify_release(_version: str, _runner: rollout.CommandRunner) -> str:
        return "a" * 40

    def status(
        _version: str, _consumers: object, _runner: rollout.CommandRunner, *, jobs: int
    ) -> tuple[rollout.Outcome, ...]:
        assert jobs == 1
        return (current,)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the public release seam keeps the activation plan test offline.
        rollout, "verify_release", verify_release
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the public fleet status seam supplies an already-current consumer.
        rollout, "status", status
    )

    with pytest.raises(rollout.RolloutError, match="separate consumer PR"):
        rollout.plan(_VERSION, (consumer,), FakeRolloutRunner(), enable_repository_rules=(_RULE,))
    assert rollout.plan(_VERSION, (consumer,), FakeRolloutRunner()).outcomes == (current,)
