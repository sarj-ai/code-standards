"""The primary CLI presents one small consumer workflow without breaking aliases."""

from __future__ import annotations

import re
import subprocess
import sys
from typing import TYPE_CHECKING, Protocol

import pytest

from sarj_lint_configs import __main__ as cli
from sarj_lint_configs import doctor, manifest


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class _DestArgs(Protocol):
    dest: str


class _CommandArgs(Protocol):
    cmd: str


def _help(*parts: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", *parts, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "legacy",
    ["sync", "list", "path", "peers", "upgrade", "verify", "format", "inspect", "repo"],
)
def test_top_level_help_prioritizes_consumer_verbs(legacy: str) -> None:
    result = _help()

    assert result.returncode == 0
    assert "{init,check,fix,doctor,update,show,maintain}" in result.stdout
    assert re.search(rf"^    {legacy}\s", result.stdout, re.MULTILINE) is None


def test_check_without_paths_runs_the_complete_check(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def verify(_args: object) -> int:
        seen.append("verify")
        return 7

    monkeypatch.setattr(cli, "cmd_verify", verify)

    assert cli.main(["check"]) == 7
    assert seen == ["verify"]


def test_check_dot_runs_the_complete_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []

    def verify(_args: object) -> int:
        seen.append("verify")
        return 0

    monkeypatch.setattr(cli, "cmd_verify", verify)

    assert cli.main(["check", "--dest", str(tmp_path), "."]) == 0
    assert seen == ["verify"]


def test_check_resolves_selected_paths_from_repository_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    seen: list[list[str]] = []

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        seen.append(list(files))
        return 0

    def clean_policy(_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)
    monkeypatch.setattr(cli, "cmd_library_policy", clean_policy)

    assert cli.main(["check", "--dest", str(tmp_path), "src/example.py"]) == 0
    assert seen == [[str(source)]]


def test_check_selected_typescript_runs_scoped_eslint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "component.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    commands = [object()]
    seen: list[tuple[Path, list[str], str]] = []

    def run_rules(_files: Sequence[str], **_kwargs: object) -> int:
        return 0

    def clean_policy(_args: object, **_kwargs: object) -> int:
        return 0

    def selected(root: Path, paths: Sequence[str], *, label: str) -> list[object]:
        seen.append((root, list(paths), label))
        return commands

    def execute(values: Sequence[object]) -> int:
        return 0 if list(values) == commands else 2

    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)
    monkeypatch.setattr(cli, "cmd_library_policy", clean_policy)
    monkeypatch.setattr("sarj_lint_configs.lifecycle.selected_eslint_commands", selected)
    monkeypatch.setattr("sarj_lint_configs.lifecycle.execute", execute)

    assert cli.main(["check", "--dest", str(tmp_path), "component.ts"]) == 0
    assert seen == [(tmp_path, [str(source)], "selected")]


def test_check_rejects_explicit_paths_outside_repository(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    assert cli.main(["check", "--dest", str(tmp_path), str(outside)]) == 2
    assert "escapes repository root" in capsys.readouterr().err


def test_check_rejects_unsupported_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check", "--format", "json"]) == 2
    assert "supported only with --dependencies" in capsys.readouterr().err


def test_check_profile_requires_dependency_mode(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(["check", "--profile", "application"])

    assert "--profile requires --dependencies" in capsys.readouterr().err


def test_full_noise_only_rejects_typescript_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    source_runs: list[list[str]] = []

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        source_runs.append(list(files))
        return 0

    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)

    assert cli.main(["check", "--noise-only", "--dest", str(tmp_path)]) == 2
    assert "no TypeScript rule subset" in capsys.readouterr().err
    assert source_runs == []


def test_full_and_selected_noise_only_share_the_manifest_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    baseline = tmp_path / ".sarj-python-baseline.json"
    baseline.write_text("{}\n", encoding="utf-8")
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=("ruff",),
        python_dest=".",
        typescript_dest=".",
        python_baseline=baseline.name,
        hook_manager="none",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    seen: list[str | None] = []

    def run_rules(
        _files: Sequence[str],
        *,
        noise_only: bool = False,
        python_baseline: str | None = None,
    ) -> int:
        assert noise_only
        seen.append(python_baseline)
        return 0

    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)

    def clean_policy(_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(cli, "cmd_library_policy", clean_policy)

    assert cli.main(["check", "--noise-only", "--dest", str(tmp_path)]) == 0
    assert cli.main(["check", "--noise-only", "--dest", str(tmp_path), "source.py"]) == 0
    assert seen == [str(baseline), str(baseline)]


def test_init_accepts_repeatable_config_before_positional_root(tmp_path: Path) -> None:
    assert cli.main(["init", "--config", "markdownlint", str(tmp_path), "--no-install"]) == 0
    assert (tmp_path / ".markdownlint.yaml").is_file()
    assert (tmp_path / ".sarj-standards.toml").is_file()


@pytest.mark.parametrize(
    ("arguments", "option"),
    [
        (["check", "--dependencies", "src"], "selected paths"),
        (["check", "--dependencies", "--staged"], "--staged"),
        (["check", "--dependencies", "--noise-only"], "--noise-only"),
        (["check", "--dependencies", "--baseline", "old.json"], "--baseline"),
        (["check", "--dependencies", "--create-baseline"], "--create-baseline"),
        (["check", "--create-baseline", "new.json", "--baseline", "old.json"], "--create-baseline"),
        (["check", "--create-baseline", "--noise-only"], "--create-baseline"),
    ],
)
def test_check_rejects_options_that_its_selected_mode_would_ignore(
    arguments: list[str],
    option: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(arguments)

    assert option in capsys.readouterr().err


def test_fix_is_a_behavior_preserving_format_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    destinations: list[str] = []

    def format_repository(args: _DestArgs) -> int:
        destinations.append(args.dest)
        return 0

    monkeypatch.setattr(cli, "cmd_format", format_repository)

    assert cli.main(["fix", str(tmp_path)]) == 0
    assert cli.main(["format", "--dest", str(tmp_path)]) == 0
    assert destinations == [str(tmp_path), str(tmp_path)]


def test_update_configs_refreshes_only_selected_config(tmp_path: Path) -> None:
    status = cli.main(["update", str(tmp_path), "--configs-only", "--config", "ruff"])

    assert status == 0
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert not (tmp_path / ".pyright-strict.json").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["update", "--config", "ruff"],
        ["update", "--force"],
        ["update", "--profile", "application"],
        ["update", "--python-dest", "python"],
        ["update", "--typescript-dest", "web"],
        ["update", "--configs-only", "--offline"],
        ["update", "--configs-only", "--no-install"],
    ],
)
def test_update_rejects_options_that_its_selected_mode_would_ignore(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(arguments)

    assert "error:" in capsys.readouterr().err


def test_check_staged_routes_only_discovered_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    staged = tmp_path / "staged.py"
    staged.write_text("value = 1\n", encoding="utf-8")
    seen: list[list[str]] = []

    def staged_files(_root: Path) -> list[str]:
        return [str(staged)]

    def run_rules(
        files: Sequence[str],
        *,
        noise_only: bool = False,
        python_baseline: str | None = None,
    ) -> int:
        _ = noise_only, python_baseline
        seen.append(list(files))
        return 0

    def clean_policy(_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(cli, "_staged_files", staged_files)
    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)
    monkeypatch.setattr(cli, "cmd_library_policy", clean_policy)

    assert cli.main(["check", "--staged", "--dest", str(tmp_path)]) == 0
    assert seen == [[str(staged)]]


def test_check_staged_filters_unsafe_hook_supplied_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kept = tmp_path / "kept.py"
    kept.write_text("value = 1\n", encoding="utf-8")
    deleted = tmp_path / "deleted.py"
    outside = tmp_path.parent / "outside.py"
    outside.write_text("value = 2\n", encoding="utf-8")
    symlink = tmp_path / "linked.py"
    symlink.symlink_to(kept)
    seen: list[list[str]] = []

    def clean_health(_root: Path, **_kwargs: object) -> int:
        return 0

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        seen.append(list(files))
        return 0

    def no_eslint(_root: Path, _paths: Sequence[str], *, label: str) -> list[object]:
        assert label == "staged"
        return []

    def clean_policy(_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(cli, "_check_staged_adoption_health", clean_health)
    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)
    monkeypatch.setattr("sarj_lint_configs.lifecycle.selected_eslint_commands", no_eslint)
    monkeypatch.setattr(cli, "cmd_library_policy", clean_policy)

    assert (
        cli.main(
            [
                "check",
                "--staged",
                "--dest",
                str(tmp_path),
                str(kept),
                str(deleted),
                str(outside),
                str(symlink),
            ]
        )
        == 0
    )
    assert seen == [[str(kept)]]


def test_check_staged_runs_scoped_eslint_and_propagates_its_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staged = tmp_path / "component.ts"
    staged.write_text("export const values = [1, 2];\n", encoding="utf-8")
    seen_paths: list[list[str]] = []
    executed: list[object] = []

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        seen_paths.append(list(files))
        return 0

    def staged_commands(root: Path, paths: Sequence[str], *, label: str) -> list[object]:
        assert root == tmp_path
        assert list(paths) == [str(staged)]
        assert label == "staged"
        return [object()]

    def execute(commands: Sequence[object]) -> int:
        executed.extend(commands)
        return 1

    def staged_files(_root: Path) -> list[str]:
        return [str(staged)]

    def clean_health(_root: Path, **_kwargs: object) -> int:
        return 0

    def clean_policy(_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(cli, "_staged_files", staged_files)
    monkeypatch.setattr(cli, "_check_staged_adoption_health", clean_health)
    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)
    monkeypatch.setattr("sarj_lint_configs.lifecycle.selected_eslint_commands", staged_commands)
    monkeypatch.setattr("sarj_lint_configs.lifecycle.execute", execute)
    monkeypatch.setattr(cli, "cmd_library_policy", clean_policy)

    assert cli.main(["check", "--staged", "--dest", str(tmp_path)]) == 1
    assert seen_paths == [[str(staged)]]
    assert len(executed) == 1


def test_check_staged_fails_on_adoption_drift_before_source_rules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged = tmp_path / "staged.py"
    staged.write_text("value = 1\n", encoding="utf-8")
    source_runs: list[list[str]] = []
    finding = doctor.Finding(
        doctor.Level.DRIFT,
        ".ruff-strict.toml",
        "ruff config differs from the installed bundle",
        "doctor.config.current",
        "run `sarj-standards update`",
    )

    def staged_files(_root: Path) -> list[str]:
        return [str(staged)]

    def diagnosed(_root: Path) -> list[doctor.Finding]:
        return [finding]

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        source_runs.append(list(files))
        return 0

    monkeypatch.setattr(cli, "_staged_files", staged_files)
    monkeypatch.setattr(doctor, "diagnose", diagnosed)
    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)

    assert cli.main(["check", "--staged", "--dest", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "drift: doctor.config.current .ruff-strict.toml" in output
    assert "fix: run `sarj-standards update`" in output
    assert source_runs == []


def test_check_staged_rejects_json_before_health_or_source_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    health_runs: list[Path] = []
    source_runs: list[list[str]] = []

    def staged_files(_root: Path) -> list[str]:
        return ["staged.py"]

    def diagnose(root: Path) -> list[doctor.Finding]:
        health_runs.append(root)
        return []

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        source_runs.append(list(files))
        return 0

    monkeypatch.setattr(cli, "_staged_files", staged_files)
    monkeypatch.setattr(doctor, "diagnose", diagnose)
    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)

    assert cli.main(["check", "--staged", "--format", "json", "--dest", str(tmp_path)]) == 2
    assert "supported only with --dependencies" in capsys.readouterr().err
    assert health_runs == []
    assert source_runs == []


def test_check_staged_returns_invalid_for_malformed_adopted_package_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "package.json").write_text('{"name": "web"}\n', encoding="utf-8")
    assert cli.main(["init", "--dest", str(tmp_path), "--no-install"]) == 0
    capsys.readouterr()
    (tmp_path / "package.json").write_text("{\n", encoding="utf-8")
    staged = tmp_path / "component.ts"
    staged.write_text("export const value = 1;\n", encoding="utf-8")
    source_runs: list[list[str]] = []

    def staged_files(_root: Path) -> list[str]:
        return [str(staged)]

    monkeypatch.setattr(cli, "_staged_files", staged_files)

    def run_rules(files: Sequence[str], **_kwargs: object) -> int:
        source_runs.append(list(files))
        return 0

    monkeypatch.setattr("sarj_lint_configs.runner.run", run_rules)

    assert cli.main(["check", "--staged", "--dest", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert "drift: doctor.package-json.invalid package.json" in output
    assert "fix: repair package.json, then rerun doctor" in output
    assert source_runs == []


def test_show_config_matches_legacy_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["show", "config", "ruff"]) == 0
    canonical = capsys.readouterr().out
    assert cli.main(["path", "ruff"]) == 0
    legacy = capsys.readouterr().out

    assert canonical == legacy


def test_maintain_preserves_the_repo_router(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    def route(args: _CommandArgs) -> int:
        commands.append(args.cmd)
        return 0

    monkeypatch.setattr(cli, "_cmd_repo", route)

    assert cli.main(["maintain", "setup", "--check"]) == 0
    assert cli.main(["repo", "setup", "--check"]) == 0
    assert commands == ["maintain", "repo"]
