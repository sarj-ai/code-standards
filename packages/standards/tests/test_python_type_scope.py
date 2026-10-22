from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue
import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting import external as external_module
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external, parse_basedpyright, run_process


if TYPE_CHECKING:
    from collections.abc import Sequence


class _TypeSummary(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore", strict=True)

    files_analyzed: int = Field(alias="filesAnalyzed", ge=0)


class _TypeReport(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore", strict=True)

    summary: _TypeSummary


class _BaselineState(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)

    files: dict[str, list[JsonValue]]


@pytest.mark.parametrize("selection", ["file", "directory"])
@pytest.mark.parametrize("invalid", [False, True], ids=["clean-import", "cross-module-type-error"])
def test_native_python_selection_preserves_project_config_and_diagnostics(
    tmp_path: Path, selection: str, invalid: bool
) -> None:
    project = tmp_path / "python project"
    project.mkdir()
    contracts = tmp_path / "shared contracts"
    contracts.mkdir()
    (contracts / "contracts.py").write_text("def number() -> int:\n    return 1\n", encoding="utf-8")
    (project / "pyrightconfig.json").write_text(
        json.dumps({"include": ["."], "extraPaths": ["../shared contracts"], "typeCheckingMode": "strict"}),
        encoding="utf-8",
    )
    selected = project / "selected.py"
    selected.write_text(
        "from contracts import number\n" + f"value: {'str' if invalid else 'int'} = number()\n",
        encoding="utf-8",
    )
    unselected = project / "unselected.py"
    unselected.write_text("value: bytes = 1\n", encoding="utf-8")
    analyzer = shutil.which("basedpyright")
    assert analyzer is not None, "The declared native BasedPyright dependency must be installed."
    reference = run_process((analyzer, "--outputjson"), cwd=project)
    reference_diagnostics = parse_basedpyright(reference.stdout, root=tmp_path)
    assert reference.returncode == 1
    assert any(diagnostic.location.path == "python project/unselected.py" for diagnostic in reference_diagnostics)
    outputs: list[ProcessOutput] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        output = run_process(argv, cwd=cwd)
        outputs.append(output)
        return output

    reports = analyze_external(
        [str(selected if selection == "file" else project)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=runner,
        capabilities=frozenset({"pyright"}),
    )

    assert len(reports) == len(outputs) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert not reports[0].issues
    expected_paths = {"python project/selected.py"}
    if selection == "directory":
        expected_paths.add("python project/unselected.py")
    expected = tuple(diagnostic for diagnostic in reference_diagnostics if diagnostic.location.path in expected_paths)
    assert reports[0].diagnostics == expected
    assert len(expected) == int(invalid) + int(selection == "directory")
    assert all(diagnostic.code == "reportAssignmentType" for diagnostic in expected)
    reference_count = _TypeReport.model_validate_json(reference.stdout).summary.files_analyzed
    actual_count = _TypeReport.model_validate_json(outputs[0].stdout).summary.files_analyzed
    if selection == "file":
        assert actual_count < reference_count
    else:
        assert actual_count == reference_count


def test_native_scoped_types_preserve_baseline_and_full_project_diagnostics(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyrightconfig.json").write_text(
        '{"include":["."],"baselineFile":"debt.json","typeCheckingMode":"strict"}', encoding="utf-8"
    )
    selected = project / "selected.py"
    selected.write_text('value: int = "old"\n', encoding="utf-8")
    (project / "unselected.py").write_text('value: int = "retained"\n', encoding="utf-8")
    analyzer = shutil.which("basedpyright")
    assert analyzer is not None, "The declared native BasedPyright dependency must be installed."
    initialized = run_process((analyzer, "--writebaseline", "--outputjson"), cwd=project)
    assert initialized.returncode in {0, 1}, initialized.stderr
    baseline = project / "debt.json"
    before = baseline.read_bytes()
    original = _BaselineState.model_validate_json(before)
    assert sorted(Path(name).as_posix() for name in original.files) == ["selected.py", "unselected.py"]
    retained_entries = {
        name: entries for name, entries in original.files.items() if Path(name) == Path("unselected.py")
    }
    selected.write_text("value: int = 1\n", encoding="utf-8")
    reference = tmp_path / "reference"
    shutil.copytree(project, reference)
    full = run_process((analyzer, "--baselinemode=auto", "--outputjson"), cwd=reference)
    assert full.returncode == 0, full.stderr
    assert parse_basedpyright(full.stdout, root=reference) == ()
    assert _BaselineState.model_validate_json((reference / "debt.json").read_bytes()).files == retained_entries
    for source, expected in (("value: int = 1\n", 0), ('value: int = 1\nnew: int = "new"\n', 1)):
        selected.write_text(source, encoding="utf-8")
        (reference / "selected.py").write_text(source, encoding="utf-8")
        full = run_process((analyzer, "--baselinemode=auto", "--outputjson"), cwd=reference)
        reports = analyze_external(
            [str(selected)], root=project, trust=TrustMode.SAFE, capabilities=frozenset({"pyright"})
        )
        assert len(reports) == 1
        assert reports[0].completion is Completion.COMPLETE
        assert not reports[0].issues
        assert reports[0].diagnostics == parse_basedpyright(full.stdout, root=reference)
        assert len(reports[0].diagnostics) == expected
        assert baseline.read_bytes() == before


@pytest.mark.parametrize("arguments", [(), (".",)], ids=["implicit-root", "explicit-root"])
def test_full_cli_keeps_the_configured_python_project_scope(
    tmp_path: Path, arguments: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = tmp_path / "src"
    sources.mkdir()
    (sources / "checked.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    (tmp_path / "excluded.py").write_text('VALUE: int = "excluded error"\n', encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text(
        '{"include":["src"],"exclude":["excluded.py"],"typeCheckingMode":"strict"}', encoding="utf-8"
    )
    commands: list[tuple[str, ...]] = []
    outputs: list[ProcessOutput] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        output = run_process(argv, cwd=cwd)
        if Path(argv[0]).name == "basedpyright":
            commands.append(tuple(argv))
            outputs.append(output)
        return output

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the native analyzer boundary while exercising full CLI routing.
        external_module, "run_process", runner
    )
    status = cli.main(["--root", str(tmp_path), "analyze", *arguments, "--external", "--format", "json"])
    capsys.readouterr()

    assert status in {0, 1}
    assert len(commands) == len(outputs) == 1
    assert commands[0][1:] == ("--outputjson",)
    assert outputs[0].returncode == 0
    assert parse_basedpyright(outputs[0].stdout, root=tmp_path) == ()
    assert _TypeReport.model_validate_json(outputs[0].stdout).summary.files_analyzed == 1


def test_unsupported_project_analyzer_fails_without_touching_baseline(tmp_path: Path) -> None:
    source = tmp_path / "selected.py"
    source.write_text("VALUE: int = 1\n", encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text('{"baselineFile":"debt.json"}', encoding="utf-8")
    baseline = tmp_path / "debt.json"
    baseline.write_text('{"files":{}}\n', encoding="utf-8")
    before = baseline.read_bytes()
    analyzer = tmp_path / ".venv" / "bin" / "basedpyright"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("#!/bin/sh\nprintf '%s\\n' 'unsupported option --baselinemode' >&2\nexit 4\n", encoding="utf-8")
    analyzer.chmod(0o755)

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"pyright"}))

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert not reports[0].diagnostics
    assert len(reports[0].issues) == 1
    assert reports[0].issues[0].kind == "tool-failure"
    assert baseline.read_bytes() == before
