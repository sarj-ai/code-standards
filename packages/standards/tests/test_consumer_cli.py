"""The public CLI is intentionally small, coherent, and repository-rooted."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.api import Standards
import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption.manifest import as_table, list_field


if TYPE_CHECKING:
    from pathlib import Path


PUBLIC_COMMANDS = ("setup", "check", "fix", "doctor", "update", "exclude", "show", "maintain")
REMOVED_ALIASES = ("init", "sync", "analyze", "verify", "format", "inspect", "upgrade", "repo", "list", "path", "peers")


def _help(*parts: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sarj_standards", *parts, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_top_level_help_exposes_only_the_clean_public_verbs() -> None:
    result = _help()
    assert result.returncode == 0
    assert all(command in result.stdout for command in PUBLIC_COMMANDS)
    assert "{setup,check,fix,doctor,update,exclude,show,maintain}" in result.stdout


@pytest.mark.parametrize("alias", REMOVED_ALIASES)
def test_removed_aliases_fail_with_a_usage_error(alias: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_standards", alias],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_setup_uses_one_global_repository_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )
    assert cli.main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    assert (tmp_path / ".sarj-standards.toml").is_file()
    assert (tmp_path / ".github" / "workflows" / "standards.yml").is_file()


def test_global_root_is_equally_valid_after_the_command(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")

    assert cli.main(["setup", "--root", str(tmp_path), "--no-install"]) == 0
    assert cli.main(["doctor", "--root", str(tmp_path)]) == 0
    assert cli.main(["exclude", "list", "--root", str(tmp_path)]) == 0


def test_show_config_and_state_are_first_class(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["show", "config", "ruff"]) == 0
    assert capsys.readouterr().out.strip().endswith("ruff.strict.toml")
    assert cli.main(["--root", str(tmp_path), "show", "state"]) == 0
    state: object = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    assert as_table(state).get("adopted_version") is None


def test_check_rejects_paths_outside_the_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    assert cli.main(["--root", str(tmp_path), "check", str(outside)]) == 2
    assert "escapes repository root" in capsys.readouterr().err


def test_machine_check_output_is_written_atomically(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    assert cli.main(["--root", str(tmp_path), "check", "--format", "json", "--output", "report.json", "source.py"]) == 0
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["schemaVersion"] == 1


def test_full_machine_check_runs_doctor_and_config_sync_gates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )
    assert cli.main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    _ = capsys.readouterr()
    (tmp_path / ".ruff-strict.toml").write_text("# stale\n", encoding="utf-8")

    status = cli.main(["--root", str(tmp_path), "check", "--format", "json"])

    payload: object = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    document = as_table(payload)
    diagnostics = tuple(as_table(item) for item in list_field(document, "diagnostics"))
    assert status == 1
    assert document.get("schemaVersion") == 1
    assert document.get("exitCode") == 1
    assert any(item.get("source") == "sarj-standards-doctor" for item in diagnostics)


def test_check_rejects_output_outside_repository_before_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def forbidden_analysis(*_args: object, **_kwargs: object) -> object:
        pytest.fail("analysis ran before report output validation")

    monkeypatch.setattr(Standards, "analyze", forbidden_analysis)

    status = cli.main(["--root", str(tmp_path), "check", "--format", "json", "--output", "../report.json", "source.py"])

    assert status == 2
    assert "report output must stay inside repository root" in capsys.readouterr().err
