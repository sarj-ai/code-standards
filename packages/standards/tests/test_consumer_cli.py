"""The public CLI is intentionally small, coherent, and repository-rooted."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.api import Standards
import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.adoption.manifest import as_table, list_field


if TYPE_CHECKING:
    from pathlib import Path


PUBLIC_COMMANDS = ("setup", "check", "fix", "doctor", "update", "ratchet", "exclude", "show", "maintain")
REMOVED_ALIASES = ("init", "sync", "analyze", "verify", "format", "inspect", "upgrade", "repo", "list", "path", "peers")


def _git_environment() -> dict[str, str]:
    """Keep hook-owned Git index variables out of nested repository fixtures."""
    return {
        key: value
        for key, value in os.environ.items()  # ruff: ignore[banned-api] — fixture must remove hook-owned Git variables.
        if not key.startswith("GIT_")
    }


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
    assert "{setup,check,observe,fix,doctor,update,ratchet,exclude,show,maintain}" in result.stdout


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


def test_global_root_equals_form_is_valid_after_the_command(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")

    assert cli.main(["setup", f"--root={tmp_path}", "--no-install"]) == 0
    assert cli.main(["doctor", f"--root={tmp_path}"]) == 0
    assert cli.main(["exclude", "list", f"--root={tmp_path}"]) == 0


def test_yarn_workspace_setup_doctor_and_check_share_an_executable_eslint_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    web = tmp_path / "apps" / "web"
    source = web / "src"
    source.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "workspace",
                "private": True,
                "packageManager": "yarn@4.15.0",
                "workspaces": ["apps/*"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "yarn.lock").write_text("__metadata:\n  version: 8\n", encoding="utf-8")
    (web / "package.json").write_text('{"name":"web","private":true,"type":"module"}\n', encoding="utf-8")
    (source / "index.ts").write_text("export {};\n", encoding="utf-8")
    binaries = tmp_path / "test-bin"
    binaries.mkdir()
    yarn_shim = binaries / "yarn_shim.py"
    yarn_shim.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "arguments = sys.argv[1:]\n"
        "if arguments[:1] == ['install']:\n"
        "    Path('.pnp.cjs').touch()\n"
        "    raise SystemExit(0)\n"
        "if arguments[:2] == ['exec', 'eslint'] and '\"eslint\"' in Path('package.json').read_text():\n"
        "    print('[]')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(127)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        (binaries / "yarn.cmd").write_text(
            f'@"{sys.executable}" "{yarn_shim}" %*\r\n',
            encoding="utf-8",
        )
    else:
        yarn = binaries / "yarn"
        yarn.write_text(f"#!{sys.executable}\n{yarn_shim.read_text(encoding='utf-8')}", encoding="utf-8")
        yarn.chmod(0o755)
    monkeypatch.setenv(
        "PATH",
        f"{binaries}{os.pathsep}{os.environ['PATH']}",  # ruff: ignore[banned-api] -- retain the test runner's tool path behind the fake Yarn executable.
    )

    assert (
        cli.main(
            [
                "--root",
                str(tmp_path),
                "setup",
                "--hooks",
                "none",
                "--typescript-dest",
                "apps/web",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "doctor"]) == 0
    _ = capsys.readouterr()
    assert cli.main(["--root", str(tmp_path), "check", "--trust-repository-code"]) == 0

    root_package: object = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    web_package: object = json.loads((web / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    assert "resolutions" in as_table(root_package)
    assert manifest.eslint_peers().items() <= manifest.table_field(as_table(web_package), "devDependencies").items()


def test_unified_ratchet_initializes_and_checks_a_suppression_budget(tmp_path: Path) -> None:
    package = tmp_path / "service"
    package.mkdir()
    (package / "app.py").write_text("value = 1  # noqa: E501\n", encoding="utf-8")

    assert cli.main(["--root", str(tmp_path), "ratchet", "init"]) == 0
    assert (tmp_path / "suppression-baseline.json").is_file()
    assert cli.main(["--root", str(tmp_path), "ratchet", "check"]) == 0


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


@pytest.mark.parametrize("output_format", ["json", "sarif"])
def test_machine_check_serializes_invalid_explicit_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    status = cli.main(["--root", str(tmp_path), "check", "--format", output_format, "missing.py"])

    output = capsys.readouterr()
    assert status == 2
    assert output.out
    assert not output.err
    assert "invalid-input" in output.out


def test_machine_check_tells_an_unadopted_repository_to_run_setup(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = cli.main(["--root", str(tmp_path), "check", "--format", "json"])

    output = capsys.readouterr()
    assert status == 1
    assert "doctor.manifest.absent" in output.out
    assert "sarj-standards setup" in output.out
    assert "sarj-standards update" not in output.out


@pytest.mark.parametrize("output_format", ["json", "sarif", "github"])
def test_staged_adoption_drift_uses_the_requested_machine_format(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nversion="0"\nrequires-python=">=3.14"\n',
        encoding="utf-8",
    )
    git_environment = _git_environment()
    _ = subprocess.run(("git", "init"), cwd=tmp_path, check=True, capture_output=True, env=git_environment)
    assert cli.main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    _ = capsys.readouterr()
    config = tmp_path / ".ruff-strict.toml"
    config.write_text("# stale\n", encoding="utf-8")
    _ = subprocess.run(
        ("git", "add", ".ruff-strict.toml"),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=git_environment,
    )

    status = cli.main(["--root", str(tmp_path), "check", "--staged", "--format", output_format])

    output = capsys.readouterr()
    assert status == 1
    assert not output.err
    if output_format == "github":
        assert output.out.startswith("::error")
    else:
        assert json.loads(output.out)


def test_machine_check_output_is_written_atomically(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    assert cli.main(["--root", str(tmp_path), "check", "--format", "json", "--output", "report.json", "source.py"]) == 0
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["schemaVersion"] == 1


def test_machine_check_creates_a_safe_nested_report_directory(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")

    status = cli.main(
        ["--root", str(tmp_path), "check", "--format", "sarif", "--output", "reports/standards.sarif", "source.py"]
    )

    assert status == 0
    assert json.loads((tmp_path / "reports" / "standards.sarif").read_text(encoding="utf-8"))["version"] == "2.1.0"


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
