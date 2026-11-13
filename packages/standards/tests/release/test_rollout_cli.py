from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner


if TYPE_CHECKING:
    from pathlib import Path


def test_release_probe_needs_no_registry_and_reports_immutable_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sha = "a" * 40
    runner = FakeRolloutRunner(
        [
            (0, "code-standards 8.38.1"),
            (0, f"{'b' * 40}\trefs/tags/standards-v8.38.1\n{sha}\trefs/tags/standards-v8.38.1^{{}}\n"),
        ]
    )
    assert (
        rollout.main(
            ["--registry", str(tmp_path / "absent.toml"), "verify-release", "--version", "8.38.1"], runner=runner
        )
        == 0
    )
    assert parse_json(capsys.readouterr().out) == {"version": "8.38.1", "source_sha": sha}
    assert len(runner.commands) == 2


def test_release_verification_waits_for_tag_without_reinstalling_published_cli() -> None:
    sha = "a" * 40
    runner = FakeRolloutRunner(
        [
            (0, "code-standards 8.38.1"),
            (0, ""),
            (0, f"{'b' * 40}\trefs/tags/standards-v8.38.1\n{sha}\trefs/tags/standards-v8.38.1^{{}}\n"),
        ]
    )
    sleeps: list[float] = []
    assert rollout.verify_release("8.38.1", runner, sleep=sleeps.append) == sha
    assert sleeps == [rollout.RELEASE_VISIBILITY_DELAY.total_seconds()]
    assert runner.commands[1] == runner.commands[2]
    assert sum(command[0] == "uvx" for command in runner.commands) == 1


def test_release_verification_bounds_missing_tag_wait() -> None:
    runner = FakeRolloutRunner([(0, "code-standards 8.38.1"), *[(0, "")] * rollout.RELEASE_VISIBILITY_ATTEMPTS])
    sleeps: list[float] = []
    with pytest.raises(rollout.RolloutError, match="absent or invalid"):
        rollout.verify_release("8.38.1", runner, sleep=sleeps.append)
    assert len(sleeps) == rollout.RELEASE_VISIBILITY_ATTEMPTS - 1


@pytest.mark.parametrize("refs", ["lightweight", "malformed", "unrelated"])
def test_release_verification_rejects_invalid_tags_without_waiting(refs: str) -> None:
    tag = "refs/tags/standards-v8.38.1"
    output = {
        "lightweight": f"{'a' * 40}\t{tag}\n",
        "malformed": f"invalid\t{tag}\n{'a' * 40}\t{tag}^{{}}\n",
        "unrelated": f"{'a' * 40}\trefs/tags/other\n{'a' * 40}\t{tag}^{{}}\n",
    }[refs]
    runner = FakeRolloutRunner([(0, "code-standards 8.38.1"), (0, output)])
    sleeps: list[float] = []
    with pytest.raises(rollout.RolloutError, match="absent or invalid"):
        rollout.verify_release("8.38.1", runner, sleep=sleeps.append)
    assert not sleeps


@pytest.mark.parametrize("command", ["plan", "apply", "status", "reconcile"])
@pytest.mark.parametrize("preserve_baselines", [False, True])
def test_rollout_cli_preserves_command_options(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preserve_baselines: bool
) -> None:
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
        if preserve_baselines:
            argv.append("--preserve-baselines")

    assert rollout.main(argv, runner=runner) == 1
    assert calls == [
        rollout.RolloutArgs(
            registry=path,
            command=rollout.RolloutCommand(command),
            version="7.10.2",
            channel=rollout.RolloutChannel.CANARY,
            dry_run=command in {"apply", "reconcile"},
            preserve_baselines=preserve_baselines and command in {"apply", "reconcile"},
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


def test_preservation_keeps_existing_rollout_argument_positions() -> None:
    args = rollout.RolloutArgs(
        rollout.DEFAULT_REGISTRY, rollout.RolloutCommand.APPLY, "8.38.1", False, rollout.RolloutChannel.CANARY
    )

    assert args.channel is rollout.RolloutChannel.CANARY
    assert not args.preserve_baselines


@pytest.mark.parametrize(
    "command",
    [
        rollout.RolloutCommand.PLAN,
        rollout.RolloutCommand.APPLY,
        rollout.RolloutCommand.STATUS,
        rollout.RolloutCommand.VERIFY_RELEASE,
    ],
)
def test_missing_exact_version_never_reads_registry_or_launches_commands(
    command: rollout.RolloutCommand, tmp_path: Path
) -> None:
    runner = FakeRolloutRunner()
    args = rollout.RolloutArgs(registry=tmp_path / "absent.toml", command=command)
    with pytest.raises(rollout.RolloutError, match="requires an exact published version"):
        rollout.execute(args, runner)
    assert runner.commands == []


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf"), 0, -1, True])
def test_invalid_timeout_never_starts_a_rollout_or_subprocess(timeout: float) -> None:
    runner = FakeRolloutRunner()
    args = rollout.RolloutArgs(command=rollout.RolloutCommand.RECONCILE, command_timeout=timeout)
    with pytest.raises(rollout.RolloutError, match="finite and positive"):
        rollout.execute(args, runner)
    with pytest.raises(rollout.RolloutError, match="finite and positive"):
        rollout.SubprocessRunner(command_timeout=timeout)
    assert runner.commands == []


@pytest.mark.parametrize("jobs", [True, 0, -1, rollout.MAX_CONCURRENT_CONSUMERS + 1])
def test_invalid_concurrency_never_starts_a_rollout(jobs: int) -> None:
    runner = FakeRolloutRunner()
    with pytest.raises(rollout.RolloutError, match="consumer concurrency limit"):
        rollout.execute(rollout.RolloutArgs(command=rollout.RolloutCommand.RECONCILE, jobs=jobs), runner)
    assert runner.commands == []


@pytest.mark.parametrize(
    "url",
    ["", "https://pr/1", "https://github.com/example/consumer/pull/0", "https://github.com/example/consumer/issues/1"],
)
def test_invalid_provider_url_cannot_qualify_a_merged_rollout(url: str) -> None:
    consumer = rollout.Consumer("Consumer", "example/consumer", "main", ("true",))
    version = "9.32.1"
    provider = [
        {
            "url": url,
            "mergedAt": "2026-11-13T00:00:00Z",
            "headRefName": rollout.rollout_branch(version),
            "baseRefName": "main",
            "body": rollout.pr_marker(consumer, version) + "\n" + rollout.desired_marker(version),
        }
    ]
    runner = FakeRolloutRunner([(0, json.dumps(provider))])
    with pytest.raises(rollout.RolloutError, match="valid GitHub pull-request URL"):
        rollout.status_one(consumer, version, runner)
    assert len(runner.commands) == 1
