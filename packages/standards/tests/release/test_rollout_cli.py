from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("command", ["plan", "apply", "status", "reconcile"])
def test_rollout_cli_preserves_command_options(command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[rollout.RolloutArgs] = []
    runner = FakeRolloutRunner()

    def execute(args: rollout.RolloutArgs, supplied: rollout.CommandRunner) -> int:
        assert supplied is runner
        calls.append(args)
        return 1

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test records CLI rollout dispatch without changing repositories
        rollout, "execute", execute
    )
    path = tmp_path / "fleet.toml"
    argv = [
        "--registry",
        str(path),
        "--require-repository",
        "sarj-ai/platform",
        command,
        "--version",
        "7.10.2",
        "--channel",
        "canary",
    ]
    if command in {"apply", "reconcile"}:
        argv.append("--dry-run")

    assert rollout.main(argv, runner=runner) == 1
    assert calls == [
        rollout.RolloutArgs(
            registry=path,
            required_repositories=("sarj-ai/platform",),
            command=command,
            version="7.10.2",
            channel="canary",
            dry_run=command in {"apply", "reconcile"},
        )
    ]


def test_rollout_rejects_a_missing_required_consumer_before_network(tmp_path: Path) -> None:
    registry = tmp_path / "fleet.toml"
    registry.write_text(
        'schema = 1\n[[consumer]]\nname = "Other"\nrepository = "sarj-ai/other"\n'
        'branch = "main"\nverify = ["make", "check"]\n',
        encoding="utf-8",
    )
    args = rollout.RolloutArgs(registry=registry, required_repositories=("sarj-ai/platform",), command="plan")

    with pytest.raises(rollout.RolloutError, match="registry omits required consumer repositories: sarj-ai/platform"):
        rollout.execute(args, FakeRolloutRunner())


@pytest.mark.parametrize(
    "argv",
    [[], ["plan"], ["apply", "--version", "1.0.0", "--channel", "unknown"]],
    ids=["missing-command", "missing-version", "invalid-channel"],
)
def test_rollout_cli_rejects_invalid_arguments_before_execution(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def execute(_args: rollout.RolloutArgs, _runner: rollout.CommandRunner) -> int:
        pytest.fail("invalid arguments must not execute a rollout")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test proves invalid CLI input never reaches rollout execution
        rollout, "execute", execute
    )

    with pytest.raises(SystemExit) as stopped:
        rollout.main(argv, runner=FakeRolloutRunner())
    assert stopped.value.code == 2


def test_reconcile_cli_preserves_optional_latest_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def execute(args: rollout.RolloutArgs, _runner: rollout.CommandRunner) -> int:
        assert args.version is None
        assert args.channel == "stable"
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test records reconcile dispatch without changing repositories
        rollout, "execute", execute
    )

    assert rollout.main(["reconcile"], runner=FakeRolloutRunner()) == 0


def test_rollout_cli_preserves_short_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert rollout.main(["-h"]) == 0
    assert "reconcile" in capsys.readouterr().out
