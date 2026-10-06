from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.json_boundary import parse_json
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
    argv = ["--registry", str(path), command, "--version", "7.10.2", "--channel", "canary"]
    if command in {"apply", "reconcile"}:
        argv.extend(("--dry-run", "--consumer", "sarj-ai/platform@dev"))

    assert rollout.main(argv, runner=runner) == 1
    assert calls == [
        rollout.RolloutArgs(
            registry=path,
            command=rollout.RolloutCommand(command),
            version="7.10.2",
            channel=rollout.RolloutChannel.CANARY,
            dry_run=command in {"apply", "reconcile"},
            consumer="sarj-ai/platform@dev" if command in {"apply", "reconcile"} else None,
        )
    ]


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


def test_consumers_cli_lists_channel_identities(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(
        "schema = 1\n\n"
        '[[consumer]]\nname = "Early"\nrepository = "example/early"\nbranch = "main"\nverify = ["true"]\n'
        'channel = "early"\n\n'
        '[[consumer]]\nname = "Stable"\nrepository = "example/stable"\nbranch = "dev"\nverify = ["true"]\n',
        encoding="utf-8",
    )

    assert rollout.main(["--registry", str(path), "consumers", "--channel", "early"]) == 0
    assert parse_json(capsys.readouterr().out) == [{"name": "Early", "identity": "example/early@main"}]
    assert rollout.main(["--registry", str(path), "consumers"]) == 0
    assert parse_json(capsys.readouterr().out) == [
        {"name": "Early", "identity": "example/early@main"},
        {"name": "Stable", "identity": "example/stable@dev"},
    ]


@pytest.mark.parametrize("registry", ["", "schema = 2\n"], ids=("empty", "unsupported"))
def test_consumers_cli_rejects_an_unusable_registry(
    registry: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "fleet.toml"
    path.write_text(registry, encoding="utf-8")

    assert rollout.main(["--registry", str(path), "consumers"]) == 2
    assert "standards-rollout:" in capsys.readouterr().err
