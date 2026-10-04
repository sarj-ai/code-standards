from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external, parse_oxlint


if TYPE_CHECKING:
    from collections.abc import Sequence


def _finding(filename: str, *, code: str = "@sarj(probe)", offset: int = 0, length: int = 8) -> dict[str, object]:
    return {
        "filename": filename,
        "code": code,
        "message": "fixture finding",
        "severity": "error",
        "labels": [{"span": {"offset": offset, "length": length}}],
    }


def _report(*diagnostics: dict[str, object], count: int = 1) -> str:
    return json.dumps({"diagnostics": diagnostics, "number_of_files": count})


def _project(root: Path) -> None:
    (root / "oxlint.config.mjs").write_text("export default {};\n", encoding="utf-8")


def test_oxlint_preserves_canonical_identity_and_utf8_spans(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text('const text = "ع🙂"; debugger;\n', encoding="utf-8")
    diagnostic = parse_oxlint(
        _report(_finding("app.ts", code="eslint(no-debugger)", offset=23, length=9)), root=tmp_path
    )[0]
    assert diagnostic.code == diagnostic.rule_id == "no-debugger"
    assert diagnostic.source == "oxlint"
    assert diagnostic.location.region is not None
    assert diagnostic.location.region.start.character == 20
    assert diagnostic.location.region.start.byte_offset == 23
    assert diagnostic.location.region.end.byte_offset == 32


def test_oxlint_discovers_exact_files_before_lint_and_reports_findings(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("debugger;\n", encoding="utf-8")
    _project(tmp_path)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return (
            ProcessOutput(0, "app.ts\n", "") if "--debug" in argv else ProcessOutput(1, _report(_finding("app.ts")), "")
        )

    report = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=runner, capabilities=frozenset({"oxlint"})
    )[0]
    assert report.completion is Completion.COMPLETE
    assert report.diagnostics[0].code == "@sarj/probe"
    assert report.file_count == 1
    assert len(seen) == 2
    assert "--debug" in seen[0]
    assert "--debug" not in seen[1]
    executable = seen[1].index("oxlint")
    assert seen[1][executable + 1 : executable + 3] == ("--format", "json")


@pytest.mark.parametrize("discovery", ["", "other.ts\n", "app.ts\nother.ts\n"])
def test_oxlint_fails_when_discovery_does_not_match_selection(tmp_path: Path, discovery: str) -> None:
    source = tmp_path / "app.ts"
    source.write_text("debugger;\n", encoding="utf-8")
    _project(tmp_path)
    calls = 0

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal calls
        assert cwd == tmp_path
        calls += 1
        assert "--debug" in argv
        return ProcessOutput(0, discovery, "")

    report = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=runner, capabilities=frozenset({"oxlint"})
    )[0]
    assert calls == (2 if not discovery else 1)
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "coverage-missing"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_report(count=0), id="missing-file-count"),
        pytest.param(_report(_finding("other.ts")), id="unselected-diagnostic"),
    ],
)
def test_oxlint_fails_when_lint_disagrees_with_discovered_files(tmp_path: Path, payload: str) -> None:
    for filename in ("app.ts", "other.ts"):
        (tmp_path / filename).write_text("debugger;\n", encoding="utf-8")
    _project(tmp_path)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(0, "app.ts\n" if "--debug" in argv else payload, "")

    report = analyze_external(
        [str(tmp_path / "app.ts")],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=runner,
        capabilities=frozenset({"oxlint"}),
    )[0]
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind in {"coverage-missing", "coverage-mismatch"}


@pytest.mark.parametrize("severity", [99, True, "fatal"])
def test_native_parser_rejects_invalid_severity(tmp_path: Path, severity: object) -> None:
    item = _finding("app.ts")
    item["severity"] = severity
    with pytest.raises((TypeError, ValueError)):
        parse_oxlint(_report(item), root=tmp_path)


@pytest.mark.parametrize("offset", [True, -1, "1"])
def test_native_parser_rejects_invalid_byte_offsets(tmp_path: Path, offset: object) -> None:
    (tmp_path / "app.ts").write_text("debugger;", encoding="utf-8")
    item = _finding("app.ts")
    item["labels"] = [{"span": {"offset": offset, "length": 1}}]
    with pytest.raises((TypeError, ValueError)):
        parse_oxlint(_report(item), root=tmp_path)


def test_native_global_suppression_diagnostic_remains_blocking(tmp_path: Path) -> None:
    item = _finding("", code="")
    item["labels"] = []
    item["message"] = "Unused suppression entries remain"
    diagnostic = parse_oxlint(_report(item), root=tmp_path)[0]
    assert diagnostic.code == "oxlint/configuration"
    assert diagnostic.location.path == "."
    assert diagnostic.location.region is None
    assert diagnostic.severity.value == "error"


def test_native_path_level_warning_has_no_invented_coordinates(tmp_path: Path) -> None:
    item = _finding("app.ts")
    item["labels"] = []
    item["severity"] = "warning"
    diagnostic = parse_oxlint(_report(item), root=tmp_path)[0]
    assert diagnostic.location.path == "app.ts"
    assert diagnostic.location.region is None
    assert diagnostic.severity.value == "warning"


def test_selected_custom_rule_uses_native_config_composition(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("debugger;\n", encoding="utf-8")
    _project(tmp_path)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return ProcessOutput(0, "app.ts\n" if "--debug" in argv else _report(count=1), "")

    report = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=runner,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"@sarj/probe"}),
    )[0]
    assert report.completion is Completion.COMPLETE
    assert "--allow" not in seen[-1]
    selected = seen[-1][seen[-1].index("--config") + 1]
    assert Path(selected).name.startswith(".sarj-oxlint-selected-")
    assert not Path(selected).exists()
