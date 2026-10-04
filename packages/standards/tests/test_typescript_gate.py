from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer

from sarj_standards import __version__
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.diagnostics import Completion, ToolReport, TrustMode
from sarj_standards.libs.linting import typescript_gate
from sarj_standards.libs.linting.external import ProcessOutput
from sarj_standards.libs.linting.formatting import analyze_formatting


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_standards.libs.linting.policy import Policy


@pytest.mark.parametrize("directory_scope", [True, False])
def test_nested_gate_resolves_cwd_paths_and_combines_manifest_and_cli_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory_scope: bool
) -> None:
    project = tmp_path / "frontend"
    project.mkdir()
    for name in ("kept.ts", "manifest-debt.ts", "cli-fixture.ts"):
        (project / name).write_text("export const value = 1;", encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(
        Manifest(
            __version__,
            ("oxlint",),
            ".",
            "frontend",
            hook_manager="none",
            excluded_paths=("frontend/manifest-debt.ts",),
        ).render(),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    captured: list[tuple[tuple[str, ...], Path, Path]] = []

    def lint(files: Sequence[str], *, root: Path, config: Path) -> ToolReport:
        captured.append((tuple(files), root, config))
        return ToolReport("oxlint", Completion.COMPLETE)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- capture the gate-to-analyzer boundary to verify exact source, repository root, and configuration routing.
        typescript_gate, "analyze_oxlint_project", lint
    )
    paths = ["."] if directory_scope else ["kept.ts", "manifest-debt.ts", "cli-fixture.ts"]

    with pytest.raises(typer.Exit) as result:
        typescript_gate.check(config=Path("oxlint.config.mts"), paths=paths, exclude=["cli-fixture.ts"])

    assert result.value.exit_code == 0
    assert captured == [((str(project / "kept.ts"),), tmp_path, project / "oxlint.config.mts")]


def test_gate_format_flag_checks_data_files_without_formatting_excluded_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "frontend"
    project.mkdir()
    (project / ".oxfmtrc.json").write_text("{}", encoding="utf-8")
    (tmp_path / "unselected.json").write_text('{"unselected":1}', encoding="utf-8")
    for name in ("kept.json", "manifest-debt.json", "cli-fixture.md"):
        (project / name).write_text('{"value":1}', encoding="utf-8")
    (tmp_path / MANIFEST_NAME).write_text(
        Manifest(
            __version__,
            ("oxlint",),
            ".",
            "frontend",
            hook_manager="none",
            excluded_paths=("frontend/manifest-debt.json",),
        ).render(),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    commands: list[tuple[str, ...]] = []

    def lint(_files: Sequence[str], *, root: Path, config: Path) -> ToolReport:
        assert root == tmp_path
        assert config == project / "oxlint.config.mts"
        return ToolReport("oxlint", Completion.COMPLETE)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == project
        commands.append(tuple(argv))
        return ProcessOutput(1, "kept.json\n", "")

    def formatter(files: Sequence[str], *, root: Path, trust: TrustMode, policy: Policy) -> ToolReport:
        return analyze_formatting(files, root=root, trust=trust, policy=policy, runner=runner)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- isolate the lint branch while verifying formatter selection and gate exit status.
        typescript_gate, "analyze_oxlint_project", lint
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the gate boundary to inject its formatter process runner and observe exact selected argv.
        typescript_gate, "analyze_formatting", formatter
    )

    with pytest.raises(typer.Exit) as result:
        typescript_gate.check(
            config=Path("oxlint.config.mts"), paths=["."], exclude=["cli-fixture.md"], format_files=True
        )

    assert result.value.exit_code == 1
    assert len(commands) == 1
    separator = len(commands[0]) - 1 - commands[0][::-1].index("--")
    selected = {Path(value).resolve() for value in commands[0][separator + 1 :]}
    assert selected == {project / ".oxfmtrc.json", project / "kept.json"}
    assert "--list-different" in commands[0]
    assert "--write" not in commands[0]
