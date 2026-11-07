from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from repo_standards.core import commit_message

from sarj_standards import __version__
from sarj_standards.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path
    from typing import Never


def test_importing_cli_does_not_eagerly_load_command_implementations() -> None:
    script = (
        "import sys; import sarj_standards.__main__; "
        "blocked = {'typer', 'pydantic', 'sarj_standards.cli.main', "
        "'sarj_standards.libs.repository.rule_catalog_artifact'}; "
        "raise SystemExit(1 if blocked & sys.modules.keys() else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_version_probe_preserves_public_output_without_loading_analysis() -> None:
    script = (
        "import sys; "
        "from sarj_standards.__main__ import main; "
        "assert main(['--version']) == 0; "
        "assert not {'typer', 'pydantic', 'sarj_standards.cli.main'} & sys.modules.keys()"
    )
    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"code-standards {__version__}\n"


@pytest.mark.parametrize(
    "message",
    [
        "feat: add search\n",
        "[OPS-42] fix(api): preserve body\n\nBody\n\nSigned-off-by: Test <test@example.test>\n",
        "fixup! existing subject\n",
    ],
)
def test_valid_commit_message_avoids_command_imports_without_changing_file(tmp_path: Path, message: str) -> None:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(message, encoding="utf-8")
    before = path.stat()
    script = (
        "import sys; from sarj_standards.__main__ import main; "
        f"sys.argv = ['code-standards', 'commit-message', {str(path)!r}]; "
        "assert main() == 0; "
        "assert not {'typer', 'sarj_standards.cli.main'} & sys.modules.keys()"
    )
    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert not result.stderr
    assert path.read_text(encoding="utf-8") == message
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert path.stat().st_mode == before.st_mode


def test_commit_message_validation_interrupt_keeps_native_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupt(_path: Path, *, fix_safe: bool = False, allow_temporary: bool = False) -> Never:
        assert not fix_safe
        assert allow_temporary
        raise KeyboardInterrupt

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Test the CLI's global lookup; injection would change its API.
        commit_message, "check_commit_message_file", interrupt
    )
    assert main(["commit-message", str(tmp_path / "COMMIT_EDITMSG")]) == 130
    assert capsys.readouterr().err == "error: interrupted\n"


def test_update_parser_exposes_the_complete_bundle_controls() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "update", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--no-install" in result.stdout


def test_invalid_destination_uses_usage_error_exit_status(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "--root", str(tmp_path / "missing"), "doctor"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "is not a directory" in result.stderr


def test_root_is_one_explicit_global_option(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_standards",
            "--root",
            str(tmp_path),
            "doctor",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode in {0, 1}
    assert "unrecognized arguments" not in result.stderr


@pytest.mark.parametrize("root_exists", [True, False], ids=("existing-root", "missing-root"))
def test_bootstrap_rooted_version_probe_uses_executing_bundle_without_loading_cli(
    tmp_path: Path, *, root_exists: bool
) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('schema = 4\nbundle = "0.0.0"\n', encoding="utf-8")
    root = tmp_path if root_exists else tmp_path / "missing"
    arguments = ["--root", str(root), "--version"]
    script = (
        "import sys; from sarj_standards.__main__ import main; "
        f"assert main({arguments!r}) == 0; "
        "assert not {'typer', 'pydantic', 'sarj_standards.cli.main'} & sys.modules.keys()"
    )
    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"code-standards {__version__}\n"


@pytest.mark.parametrize(
    "form",
    ["rooted-help", "extra-help", "extra-command", "equals-root", "duplicate-root", "missing-root-value"],
)
def test_noncanonical_metadata_arguments_are_forwarded_to_actual_typer(tmp_path: Path, form: str) -> None:
    arguments = {
        "rooted-help": ["--root", str(tmp_path), "--help"],
        "extra-help": ["--root", str(tmp_path), "--version", "--help"],
        "extra-command": ["--root", str(tmp_path), "--version", "doctor"],
        "equals-root": [f"--root={tmp_path}", "--version"],
        "duplicate-root": ["--root", str(tmp_path), "--root", str(tmp_path), "--version"],
        "missing-root-value": ["--root"],
    }[form]
    expected = 2 if form == "missing-root-value" else 0
    script = (
        "import importlib\n"
        "cli = importlib.import_module('sarj_standards.cli.main')\n"
        "original = cli.main\n"
        "seen = []\n"
        "def forward(arguments):\n"
        "    seen.append(arguments)\n"
        "    return original(arguments)\n"
        "cli.main = forward\n"
        "from sarj_standards.__main__ import main\n"
        f"arguments = {arguments!r}\n"
        "try:\n"
        "    status = main(arguments)\n"
        "except SystemExit as error:\n"
        "    status = error.code\n"
        f"assert status == {expected}\n"
        "assert seen == [arguments]\n"
        "assert seen[0] is arguments\n"
    )
    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    match form:
        case "rooted-help":
            assert "Usage:" in result.stdout
        case "missing-root-value":
            assert "requires an argument" in result.stderr
        case _:
            assert result.stdout == f"code-standards {__version__}\n"
