from __future__ import annotations

from importlib.resources import files
import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import external, runner, stylelint
from sarj_standards.libs.linting.process import ProcessOutput
from tests.oxlint_project import project
from tests.process_fakes import FakeProcessExecutor


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from pydantic import JsonValue


def _empty_report(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
    assert cwd.is_dir()
    return ProcessOutput(0, "[]", "")


def _report(source: str, warnings: list[dict[str, JsonValue]] | None = None) -> str:
    return json.dumps([{"source": source, "warnings": warnings or []}])


def test_css_routes_without_entering_javascript_analysis(tmp_path: Path) -> None:
    path = tmp_path / "view.css"
    path.write_text(".a {}\n", encoding="utf-8")
    grouped = runner.group_paths([str(path)])
    assert grouped.css == [str(path)]
    assert grouped.typescript == []
    assert runner.accepts_hook_path(path, root=tmp_path)


def test_normalizes_css_warnings_and_unicode_locations(tmp_path: Path) -> None:
    path = tmp_path / "view.css"
    path.write_text("/* 🐈 */ .a { font-size: 16px; }\n", encoding="utf-8")
    payload = _report(
        str(path),
        [
            {
                "line": 1,
                "column": 26,
                "endLine": 1,
                "endColumn": 30,
                "rule": "declaration-property-value-disallowed-list",
                "severity": "warning",
                "text": "Use relative type.",
            }
        ],
    )
    (diagnostic,) = stylelint.parse(payload, root=tmp_path, selected=("view.css",))
    assert diagnostic.severity is Severity.WARNING
    assert diagnostic.source == "stylelint"
    assert diagnostic.location.path == "view.css"
    assert diagnostic.location.region is not None
    assert diagnostic.location.region.start.byte_offset == 27
    assert diagnostic.location.region.end.byte_offset == 31


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("[]", id="omitted-source"),
        pytest.param(_report("outside.css"), id="unexpected-source"),
        pytest.param(json.dumps([{"source": "view.css", "warnings": [], "ignored": True}]), id="ignored-source"),
        pytest.param(
            json.dumps([{"source": "view.css", "warnings": [], "invalidOptionWarnings": [{"text": "bad option"}]}]),
            id="invalid-configuration",
        ),
    ],
)
def test_rejects_missing_unexpected_ignored_and_invalid_configuration(payload: str, tmp_path: Path) -> None:
    (tmp_path / "view.css").write_text(".a {}", encoding="utf-8")
    with pytest.raises(ValueError, match="Stylelint"):
        stylelint.parse(payload, root=tmp_path, selected=("view.css",))


def test_css_execution_requires_trust(tmp_path: Path) -> None:
    (tmp_path / "view.css").write_text(".a {}", encoding="utf-8")
    process = FakeProcessExecutor(_empty_report)
    (report,) = external.analyze_external(
        ("view.css",), root=tmp_path, runner=process, trust=TrustMode.SAFE, capabilities=frozenset({"typescript"})
    )
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "trust-required"
    assert process.requests == []


def test_uses_managed_configuration_and_reports_incomplete_output(tmp_path: Path) -> None:
    (tmp_path / "view.css").write_text(".a {}", encoding="utf-8")
    process = FakeProcessExecutor(_empty_report)
    (report,) = external.analyze_external(
        ("view.css",), root=tmp_path, runner=process, trust=TrustMode.TRUSTED, capabilities=frozenset({"typescript"})
    )
    assert report.completion is Completion.FAILED
    assert "stylelint.strict.json" in " ".join(process.requests[0].argv)
    assert "--ignore-path" in process.requests[0].argv


def test_installed_css_cli_reports_managed_findings_from_a_consumer(tmp_path: Path) -> None:
    project(
        tmp_path, {"view.css": ".a { font-size: 16px; animation-timeline: scroll(); animation: reveal linear both; }"}
    )
    (report,) = external.analyze_external(
        ("view.css",), root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"typescript"})
    )
    assert report.completion is Completion.COMPLETE, report.issues
    assert {diagnostic.code for diagnostic in report.diagnostics} == {
        "declaration-property-value-disallowed-list",
        "@sarj/no-modern-shorthand-reset",
    }
    assert all(diagnostic.severity is Severity.WARNING for diagnostic in report.diagnostics)


def test_css_inventory_matches_the_shipped_warning_preset() -> None:
    config = parse_json(files("sarj_standards").joinpath("configs/stylelint.strict.json").read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    rules = config["rules"]
    assert isinstance(rules, dict)
    assert set(rules) == set(stylelint.RULES)
    assert config["defaultSeverity"] == "warning"
