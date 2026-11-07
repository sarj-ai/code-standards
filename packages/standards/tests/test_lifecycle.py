from __future__ import annotations

from importlib.metadata import version as distribution_version
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import TYPE_CHECKING, Unpack

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import doctor, lifecycle, manifest, scaffold
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting import external, oxlint_directives


if TYPE_CHECKING:
    from collections.abc import Iterable

    from tests.call_contracts import SubprocessOptions


def _unexpected_directive_command(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
    pytest.fail(f"directive platform eligibility must be checked before native execution: {command.label}")


def test_empty_directive_plan_needs_no_platform_or_repository_access(tmp_path: Path) -> None:
    missing_repository = tmp_path / "not-created"

    assert oxlint_directives.plan(missing_repository, (), run=_unexpected_directive_command) == {}
    assert not missing_repository.exists()


def test_directive_planner_checks_the_actual_host_platform_before_repository_access(tmp_path: Path) -> None:
    missing_repository = tmp_path / "not-created"

    assert oxlint_directives.SUPPORTS_DIRECTIVE_REWRITES is (os.name == "posix")
    if os.name != "posix":
        with pytest.raises(ValueError, match="require POSIX ownership and private-file permission checks"):
            oxlint_directives.plan(missing_repository, ("source.ts",), run=_unexpected_directive_command)
        assert not missing_repository.exists()


def _project(root: Path, name: str) -> Path:
    project = root / name
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n", encoding="utf-8")
    (project / "pyrightconfig.json").write_text(json.dumps({"include": ["src"]}), encoding="utf-8")
    return project


def test_verification_uses_isolated_tool_binaries_in_each_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='umbrella'\nversion='0.0.0'\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(json.dumps({"extends": ".pyright-strict.json"}), encoding="utf-8")
    first = _project(tmp_path, "packages/first")
    second = _project(tmp_path, "packages/second")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.verification_commands(ecosystems)

    assert [command.cwd for command in commands] == [first, first, second, second]
    assert {Path(command.argv[0]).stem for command in commands} == {"ruff", "basedpyright"}
    assert {command.label for command in commands} == {"Ruff", "BasedPyright"}


def test_scoped_root_pyright_config_keeps_the_root_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='root'\nversion='0.0.0'\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(json.dumps({"include": ["src"]}), encoding="utf-8")
    _project(tmp_path, "packages/child")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.verification_commands(ecosystems)

    assert tmp_path in {command.cwd for command in commands}


def test_verification_type_checks_with_the_local_tsrs_lint(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    tsrs_lint = tmp_path / "node_modules" / ".bin" / "tsrs-lint"
    tsrs_lint.parent.mkdir(parents=True)
    tsrs_lint.touch()
    ecosystems = scaffold.Ecosystems(False, True, typescript_root=tmp_path)

    [command] = lifecycle.verification_commands(ecosystems)

    assert command.argv[-2:] == ("oxlint", "--type-check")
    assert dict(command.environment) == {"OXLINT_TSGOLINT_PATH": str(tsrs_lint), "SARJ_TYPE_AWARE": "1"}


def test_fix_uses_the_isolated_ruff_without_requiring_a_consumer_lockfile(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    commands = lifecycle.format_commands(ecosystems)

    assert [command.label for command in commands] == ["Ruff fixes", "Ruff format"]
    assert {Path(command.argv[0]).stem for command in commands} == {"ruff"}
    assert commands[0].argv[1:] == ("check", "--fix", "--no-unsafe-fixes", ".")
    assert commands[1].argv[1:] == ("format", ".")
    assert all("--frozen" not in command.argv for command in commands)


def test_fix_routes_to_the_adopted_nested_typescript_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = tmp_path / "apps" / "web"
    web.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name":"workspace","private":true,"packageManager":"pnpm@11.0.0"}\n',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-workspace.yaml").write_text('packages:\n  - "apps/*"\n', encoding="utf-8")
    (web / "package.json").write_text('{"name":"web","private":true}\n', encoding="utf-8")
    (web / "view.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / ".sarj-standards.toml").write_text(
        manifest.Manifest(
            version=distribution_version("code-standards"),
            configs=("typescript",),
            python_dest=".",
            typescript_dest="apps/web",
        ).render(),
        encoding="utf-8",
    )
    planned: list[lifecycle.Command] = []

    def clean_diagnosis(_root: Path) -> list[doctor.Finding]:
        return []

    def capture(commands: Iterable[lifecycle.Command]) -> int:
        planned.extend(commands)
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts installation process routing
        doctor, "diagnose", clean_diagnosis
    )
    monkeypatch.setattr(lifecycle, "execute", capture)  # sarj-noqa: SARJ445 -- intercepts installation process routing

    assert cli.main(["--root", str(tmp_path), "fix"]) == 0
    assert [(command.label, command.cwd) for command in planned] == [
        ("Oxlint (selected: apps/web)", web),
        ("Oxlint unused directives", tmp_path),
    ]


def test_selected_fix_routes_only_the_requested_python_and_typescript_files(tmp_path: Path) -> None:
    python_file = tmp_path / "service.py"
    python_file.write_text("value=1\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"web"}\n', encoding="utf-8")
    typescript_file = tmp_path / "view.ts"
    typescript_file.write_text("export const value = 1;\n", encoding="utf-8")

    commands = lifecycle.selected_format_commands(tmp_path, (str(python_file), str(typescript_file)))

    assert [command.label for command in commands[:2]] == ["Ruff fixes", "Ruff format"]
    assert commands[0].argv[-1] == "service.py"
    assert commands[1].argv[-1] == "service.py"
    assert commands[2].argv[-3:] == ("--fix", "--", "view.ts")


def _ruff_fallback_project(root: Path, *, overrides: tuple[manifest.ExclusionOverride, ...] = ()) -> Path:
    project = root / "python"
    project.mkdir()
    config = project / "pyproject.toml"
    config.write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n[tool.ruff.lint.extend-per-file-ignores]\n"api.py" = ["F401"]\n',
        encoding="utf-8",
    )
    (project / ".ruff-strict.toml").write_text('line-length = 120\n[lint]\nselect = ["F401"]\n', encoding="utf-8")
    (root / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(
            version=distribution_version("code-standards"),
            configs=("ruff",),
            python_dest="python",
            typescript_dest=".",
            exclusion_overrides=overrides,
        ).render(),
        encoding="utf-8",
    )
    return config


def test_selected_ruff_fixes_share_checking_fallback_authority(tmp_path: Path) -> None:
    config = _ruff_fallback_project(tmp_path)
    source = tmp_path / "api.py"
    source.write_text("import os\n", encoding="utf-8")
    [(project, checked_config, checked_paths)] = external.ruff_project_groups([str(source)], tmp_path)
    commands = lifecycle.selected_format_commands(tmp_path, [str(source)])
    assert checked_config == config
    assert checked_paths == (str(source),)
    assert [command.label for command in commands] == ["Ruff fixes", "Ruff format"]
    for command in commands:
        assert command.cwd == project == tmp_path
        assert command.argv[command.argv.index("--config") + 1] == str(config)
        assert command.argv[-2:] == ("--", "api.py")
    assert "--no-unsafe-fixes" in commands[0].argv


def test_selected_ruff_fixes_keep_project_and_exclusion_groups(tmp_path: Path) -> None:
    overrides = (manifest.ExclusionOverride(paths=("excluded.py",), rules=("ruff:F401",), reason="fixture exclusion"),)
    fallback = _ruff_fallback_project(tmp_path, overrides=overrides)
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_config = nested / "ruff.toml"
    nested_config.write_text("line-length = 100\n", encoding="utf-8")
    paths = [tmp_path / "api.py", tmp_path / "excluded.py", nested / "source.py"]
    for path in paths:
        path.write_text("import os\n", encoding="utf-8")
    commands = lifecycle.selected_format_commands(tmp_path, [str(path) for path in paths])
    fixes = [command for command in commands if command.label == "Ruff fixes"]
    formats = [command for command in commands if command.label == "Ruff format"]
    assert len(fixes) == len(formats) == 3
    selected: set[Path] = set()
    for fixed, formatted in zip(fixes, formats, strict=True):
        config = Path(fixed.argv[fixed.argv.index("--config") + 1])
        assert formatted.argv[formatted.argv.index("--config") + 1] == str(config)
        assert fixed.cwd == formatted.cwd == (nested if config == nested_config else tmp_path)
        assert "--no-unsafe-fixes" in fixed.argv
        source = (fixed.cwd / fixed.argv[-1]).resolve()
        assert source == (formatted.cwd / formatted.argv[-1]).resolve()
        selected.add(source)
        assert config == (nested_config if source.parent == nested else fallback)
        assert ("--extend-ignore" in fixed.argv) == (source.name == "excluded.py")
        if source.name == "excluded.py":
            assert fixed.argv[fixed.argv.index("--extend-ignore") + 1] == "F401"
    assert selected == set(paths)


def test_selected_ruff_fixes_resolve_relative_inputs_against_root(tmp_path: Path) -> None:
    _ruff_fallback_project(tmp_path)
    source = tmp_path / "api.py"
    source.write_text("import os\n", encoding="utf-8")
    absolute = lifecycle.selected_format_commands(tmp_path, [str(source)])
    relative = lifecycle.selected_format_commands(tmp_path, ["api.py"])
    assert relative == absolute
    assert all(command.cwd == tmp_path for command in relative)


def test_selected_ruff_fixes_execute_with_fallback_per_file_ignores(tmp_path: Path) -> None:
    _ruff_fallback_project(tmp_path)
    source = tmp_path / "api.py"
    original = "import os\n"
    source.write_text(original, encoding="utf-8")
    commands = lifecycle.selected_format_commands(tmp_path, [str(source)])
    binary = commands[0].argv[0]
    default_check = subprocess.run(
        [binary, "check", "--isolated", "--select", "F401", "--", str(source)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert default_check.returncode == 1
    assert "F401" in default_check.stdout
    assert lifecycle.execute(commands) == 0
    assert source.read_text(encoding="utf-8") == original
    assert lifecycle.execute(commands) == 0
    assert source.read_text(encoding="utf-8") == original


def test_selected_ruff_formatter_executes_with_fallback_line_length(tmp_path: Path) -> None:
    _ruff_fallback_project(tmp_path)
    source = tmp_path / "values.py"
    original = 'values = ["' + "a" * 40 + '", "' + "b" * 40 + '"]\n'
    source.write_text(original, encoding="utf-8")
    commands = lifecycle.selected_format_commands(tmp_path, [str(source)])
    formatter = next(command for command in commands if command.label == "Ruff format")
    default_check = subprocess.run(
        [formatter.argv[0], "format", "--isolated", "--check", "--", str(source)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert default_check.returncode == 1
    assert lifecycle.execute((formatter,)) == 0
    assert source.read_text(encoding="utf-8") == original
    assert lifecycle.execute((formatter,)) == 0
    assert source.read_text(encoding="utf-8") == original


def _adopted_ruff_sources(root: Path) -> tuple[Path, ...]:
    project = root / "python"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[tool.ruff]\ntarget-version = "py314"\n'
        '[tool.ruff.per-file-target-version]\n"tools/legacy/**" = "py311"\n'
        '[tool.ruff.lint]\npreview = true\nselect = ["UP035", "TC002", "S404", "S603", "TRY301"]\n'
        "[tool.ruff.lint.per-file-ignores]\n"
        '"feature/**/tests/**" = ["TC002"]\n'
        '"scripts/test_command.py" = ["S404", "S603"]\n'
        '"worker/**/tests/**" = ["TRY301"]\n',
        encoding="utf-8",
    )
    (root / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(
            version=distribution_version("code-standards"),
            configs=("ruff",),
            python_dest="python",
            typescript_dest=".",
        ).render(),
        encoding="utf-8",
    )
    cases = (
        (
            "tools/legacy/settings.py",
            (
                "from typing_extensions import override\n\n\nclass Parent:\n"
                "    def run(self) -> None:\n        pass\n\n\nclass Provider(Parent):\n"
                '    @override\n    def run(self) -> None:\n        try:\n            int("value")\n'
                "        except (TypeError, ValueError):\n            pass\n"
            ),
        ),
        (
            "python/feature/tests/test_record.py",
            (
                "from __future__ import annotations\n\nfrom httpx import Client\n\n\n"
                "def consume(client: Client) -> None:\n    pass\n"
            ),
        ),
        (
            "python/scripts/test_command.py",
            (
                "import subprocess\n\n\ndef execute(command: list[str]) -> None:\n"
                "    subprocess.run(command, check=True)\n"
            ),
        ),
        (
            "python/worker/tests/test_error.py",
            (
                'def consume() -> None:\n    try:\n        raise ValueError("value")\n'
                "    except ValueError:\n        return\n"
            ),
        ),
    )
    sources: list[Path] = []
    for name, text in cases:
        source = root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")
        sources.append(source)
    legacy = root / "tools/legacy/pyproject.toml"
    legacy.write_text('[project]\nname = "legacy"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n', encoding="utf-8")
    return tuple(sources)


def test_ruff_analysis_resolves_adopted_policy_from_repository_root(tmp_path: Path) -> None:
    sources = _adopted_ruff_sources(tmp_path)
    controls = tmp_path / "controls"
    controls.mkdir()
    uncovered: list[Path] = []
    for source in sources:
        target = controls / source.name
        target.write_bytes(source.read_bytes())
        uncovered.append(target)

    reports = external.analyze_external(
        [str(source) for source in (*sources, *uncovered)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"ruff"}),
    )

    assert reports
    assert all(report.completion is Completion.COMPLETE and not report.issues for report in reports)
    findings = [finding for report in reports for finding in report.diagnostics]
    assert {finding.code for finding in findings} == {"UP035", "TC002", "S404", "S603", "TRY301"}
    assert {finding.location.path for finding in findings} == {
        source.relative_to(tmp_path).as_posix() for source in uncovered
    }


def test_ruff_fix_and_format_preserve_adopted_compatibility_and_ignores(tmp_path: Path) -> None:
    sources = _adopted_ruff_sources(tmp_path)
    originals = {source: source.read_bytes() for source in sources}
    commands = lifecycle.selected_format_commands(tmp_path, [str(source) for source in sources])

    assert lifecycle.execute(commands) == 0
    assert {source: source.read_bytes() for source in sources} == originals
    assert lifecycle.execute(commands) == 0
    assert {source: source.read_bytes() for source in sources} == originals


def test_ruff_preserves_distinct_package_config_context(tmp_path: Path) -> None:
    legacy, _, command_source, _ = _adopted_ruff_sources(tmp_path)
    project = tmp_path / "plugins/native"
    project.mkdir(parents=True)
    (project / "ruff.toml").write_text(
        'target-version = "py311"\n[lint]\npreview = true\nselect = ["UP035", "S404", "S603"]\n'
        '[lint.per-file-ignores]\n"tests/test_command.py" = ["S404", "S603"]\n',
        encoding="utf-8",
    )
    sources = (project / "settings.py", project / "tests/test_command.py")
    sources[1].parent.mkdir()
    for source, original in zip(sources, (legacy, command_source), strict=True):
        source.write_bytes(original.read_bytes())
    originals = {source: source.read_bytes() for source in sources}

    reports = external.analyze_external(
        [str(source) for source in sources],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"ruff"}),
    )
    assert reports
    assert all(report.completion is Completion.COMPLETE and not report.issues for report in reports)
    assert not [finding for report in reports for finding in report.diagnostics]
    commands = lifecycle.selected_format_commands(tmp_path, [str(source) for source in sources])
    assert all(command.cwd == project for command in commands)
    assert lifecycle.execute(commands) == 0
    assert {source: source.read_bytes() for source in sources} == originals


def test_setup_never_mutates_the_consumer_dependency_environment(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "old-python-app"\nrequires-python = ">=3.10"\n'
        '\n[dependency-groups]\ndev = ["sarj-standards==1.2.3"]\n',
        encoding="utf-8",
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    assert lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none") == []


def test_setup_does_not_install_standards_into_a_consumer_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "old-python-app"\nrequires-python = ">=3.10"\n', encoding="utf-8"
    )
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    assert lifecycle.install_commands(tmp_path, ecosystems, hook_manager="none") == []


@pytest.mark.parametrize("python", [True, False])
def test_precommit_install_includes_staged_and_message_hooks(tmp_path: Path, python: bool) -> None:
    (tmp_path / ".git").mkdir()
    ecosystems = scaffold.Ecosystems(python, not python, python_root=tmp_path if python else None)

    command = lifecycle.install_commands(tmp_path, ecosystems)[-1]

    assert command.argv[-6:] == (
        "install",
        "--hook-type",
        "pre-commit",
        "--hook-type",
        "commit-msg",
        "--install-hooks",
    )
    assert command.argv[:2] == ("uvx", "--no-config")


def test_lefthook_install_uses_the_managed_durable_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    executable = tmp_path / "code-standards"
    executable.write_text("", encoding="utf-8")

    def environment_binary(_name: str) -> str:
        return str(executable)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts installation process routing
        lifecycle, "_environment_binary", environment_binary
    )

    [command] = lifecycle.install_commands(
        tmp_path,
        scaffold.Ecosystems(False, False),
        hook_manager="lefthook",
    )

    assert command.label == "Lefthook repository hooks"
    assert command.argv == (
        str(executable),
        "--root",
        str(tmp_path),
        "maintain",
        "hooks",
        "install",
    )


@pytest.mark.parametrize("hook_type", ["post-checkout", "post-commit", "post-merge"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("backup_exists", [False, True])
@pytest.mark.parametrize("backup_suffix", ["legacy", "old"])
def test_failed_install_restores_lfs_post_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook_type: str,
    *,
    existing: bool,
    backup_exists: bool,
    backup_suffix: str,
) -> None:
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / hook_type
    backup = hooks / f"{hook_type}.{backup_suffix}"
    original_hook_mode = None
    original_backup_mode = None
    if existing:
        hook.write_text("original\n", encoding="utf-8")
        hook.chmod(0o744)
        original_hook_mode = stat.S_IMODE(hook.stat().st_mode)
    if backup_exists:
        backup.write_text("original backup\n", encoding="utf-8")
        backup.chmod(0o640)
        original_backup_mode = stat.S_IMODE(backup.stat().st_mode)

    def failed_install(argv: list[str], **_kwargs: Unpack[SubprocessOptions]) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=f".git/{argv[-1]}\n")
        if argv[1:2] == ["dump"]:
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({hook_type: {}}))
        hook.write_text("partial install\n", encoding="utf-8")
        hook.chmod(0o777)
        backup.write_text("partial backup\n", encoding="utf-8")
        backup.chmod(0o777)
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- an interrupted installer must restore every affected hook.
        "sarj_standards.libs.adoption.lifecycle.subprocess.run", failed_install
    )

    assert lifecycle.execute([lifecycle.Command("Lefthook repository hooks", (sys.executable,), tmp_path)]) == 7
    if existing:
        assert hook.read_text(encoding="utf-8") == "original\n"
        assert stat.S_IMODE(hook.stat().st_mode) == original_hook_mode
    else:
        assert not hook.exists()
    if backup_exists:
        assert backup.read_text(encoding="utf-8") == "original backup\n"
        assert stat.S_IMODE(backup.stat().st_mode) == original_backup_mode
    else:
        assert not backup.exists()


@pytest.mark.parametrize("discovery", ["rev-parse", "dump"])
def test_lefthook_preflight_timeout_prevents_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], discovery: str
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Unpack[SubprocessOptions]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[1] == discovery:
            timeout = kwargs.get("timeout")
            assert timeout == 5
            raise subprocess.TimeoutExpired(argv, timeout)
        assert argv[1] == "rev-parse"
        return subprocess.CompletedProcess(argv, 0, stdout=f".git/{argv[-1]}\n")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a stalled discovery must not start the hook installer.
        "sarj_standards.libs.repository.hooks.subprocess.run", run
    )

    assert lifecycle.execute([lifecycle.Command("Lefthook repository hooks", (sys.executable,), tmp_path)]) == 2
    assert all("install" not in argv for argv in calls)
    assert "exceeded 5s and was stopped" in capsys.readouterr().err


def test_precommit_hook_uses_pinned_uvx_after_its_install_cache_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/usr/bin/env bash\n"
        "INSTALL_PYTHON=/removed/uv-cache/archive/bin/python\n"
        "ARGS=(hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit)\n"
        'if [ -x "$INSTALL_PYTHON" ]; then\n'
        '    exec "$INSTALL_PYTHON" -mpre_commit "${ARGS[@]}"\n'
        "elif command -v pre-commit > /dev/null; then\n"
        '    exec pre-commit "${ARGS[@]}"\n'
        "else\n"
        "    exit 1\n"
        "fi\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    def installed_hook(_root: Path, *, hook_type: str = "pre-commit") -> Path:
        assert hook_type == "pre-commit"
        return hook

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts installation process routing
        "sarj_standards.libs.adoption.lifecycle._precommit_hook_path", installed_hook
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    capture = tmp_path / "uvx-args"
    uvx = binaries / "uvx"
    uvx.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n', encoding="utf-8")
    uvx.chmod(0o755)
    original_which = shutil.which

    def select_binary(name: str, mode: int = os.F_OK | os.X_OK, path: str | None = None) -> str | None:
        return str(uvx) if name == "uvx" else original_which(name, mode=mode, path=path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts installation process routing
        "sarj_standards.libs.adoption.lifecycle.shutil.which", select_binary
    )
    bash = original_which("bash")
    assert bash is not None

    lifecycle.harden_precommit_hook(tmp_path)
    completed = subprocess.run(
        (bash, str(hook)),
        check=False,
        env={"PATH": f"{binaries}{os.pathsep}/usr/bin:/bin", "CAPTURE": str(capture)},
    )

    assert completed.returncode == 0
    arguments = capture.read_text(encoding="utf-8")
    assert f"pre-commit=={distribution_version('pre-commit')}" in arguments
    assert "hook-impl" in arguments


def test_precommit_installer_hardens_the_generated_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    hardened: list[Path] = []
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts installation process routing
        lifecycle, "harden_precommit_hooks", hardened.append
    )

    status = lifecycle.execute(
        [lifecycle.Command("pre-commit hooks", (sys.executable, "-c", "raise SystemExit(0)"), tmp_path)]
    )

    assert status == 0
    assert hardened == [tmp_path]


def test_precommit_install_includes_linked_worktree_gitfile(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: ../.git/worktrees/fixture\n", encoding="utf-8")
    ecosystems = scaffold.Ecosystems(True, False, python_root=tmp_path)

    [command] = lifecycle.install_commands(tmp_path, ecosystems)

    assert command.label == "pre-commit hooks"


def test_linked_worktree_hook_survives_its_install_cache_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked checkout"
    primary.mkdir()
    subprocess.run(("git", "init", "-q", "-b", "main"), cwd=primary, check=True)
    subprocess.run(("git", "config", "user.name", "Test"), cwd=primary, check=True)
    subprocess.run(("git", "config", "user.email", "test@example.invalid"), cwd=primary, check=True)
    (primary / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=primary, check=True)
    subprocess.run(("git", "commit", "-qm", "fixture"), cwd=primary, check=True)
    subprocess.run(("git", "worktree", "add", "-q", "-b", "linked", str(linked)), cwd=primary, check=True)
    subprocess.run(
        (sys.executable, "-m", "pre_commit", "install", "--hook-type", "pre-commit"),
        cwd=linked,
        check=True,
    )
    hook = Path(
        subprocess.run(
            ("git", "rev-parse", "--git-path", "hooks/pre-commit"),
            cwd=linked,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    original_mode = hook.stat().st_mode
    cache_python = tmp_path / "deleted cache" / "bin" / "python"
    cache_python.parent.mkdir(parents=True)
    cache_python.write_text("temporary", encoding="utf-8")
    lines = hook.read_text(encoding="utf-8").splitlines()
    hook.write_text(
        "\n".join(f"INSTALL_PYTHON={cache_python}" if line.startswith("INSTALL_PYTHON=") else line for line in lines)
        + "\n",
        encoding="utf-8",
    )
    hook.chmod(original_mode)
    cache_python.unlink()
    cache_python.parent.rmdir()
    cache_python.parent.parent.rmdir()

    binaries = tmp_path / "bin"
    binaries.mkdir()
    capture = tmp_path / "uvx-args"
    uvx = binaries / "uvx"
    uvx.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n', encoding="utf-8")
    uvx.chmod(0o755)
    original_which = shutil.which

    def select_binary(name: str, mode: int = os.F_OK | os.X_OK, path: str | None = None) -> str | None:
        return str(uvx) if name == "uvx" else original_which(name, mode=mode, path=path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts installation process routing
        "sarj_standards.libs.adoption.lifecycle.shutil.which", select_binary
    )
    lifecycle.harden_precommit_hook(linked)

    bash = original_which("bash")
    assert bash is not None
    completed = subprocess.run(
        (bash, str(hook)),
        cwd=linked,
        check=False,
        env={"PATH": f"{binaries}{os.pathsep}/usr/bin:/bin", "CAPTURE": str(capture)},
    )

    assert completed.returncode == 0
    assert hook.stat().st_mode == original_mode
    assert f"pre-commit=={distribution_version('pre-commit')}" in capture.read_text(encoding="utf-8")
