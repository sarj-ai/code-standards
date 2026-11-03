from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import sarj_python_lint.__main__ as python_engine
from sarj_python_lint.rule_base import Diagnostic as PythonDiagnostic

from sarj_standards.api import AnalysisMode, Standards
from sarj_standards.libs.diagnostics import Completion, Conclusion, Position
from sarj_standards.libs.linting.external import run_process


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pytest
    from sarj_rule_contracts import SourceCatalog


def test_selected_python_analysis_imports_only_its_rule_implementation(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")
    script = """import sys
from pathlib import Path
from sarj_standards.api import AnalysisMode, Standards
from sarj_python_lint.rule_metadata import load_descriptors

report = Standards(Path(sys.argv[1])).analyze(
    ['app.py'], mode=AnalysisMode.RAW, rules=['python:no-secret-in-log']
)
assert report.completion.value == 'complete', report.issues
assert [item.code for item in report.diagnostics] == ['SARJ012']
loaded = sorted(item.rule_id for item in load_descriptors() if item.module in sys.modules)
assert loaded == ['no-secret-in-log'], loaded
"""

    result = run_process((sys.executable, "-I", "-c", script, str(tmp_path)), cwd=tmp_path, timeout_seconds=30)

    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert not result.stderr


def test_selected_metadata_preserves_global_diagnostic_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "app.py"
    path.write_text("logger.info('request', token=token)\n", encoding="utf-8")
    original = python_engine.analyze

    def with_global_diagnostic(
        rule_ids: Sequence[str],
        paths: list[Path],
        *,
        baseline: Path | None = None,
        root: Path | None = None,
        jobs: int = 1,
        sources: SourceCatalog | None = None,
    ) -> list[PythonDiagnostic]:
        findings = original(rule_ids, paths, baseline=baseline, root=root, jobs=jobs, sources=sources)
        return [*findings, PythonDiagnostic(path, 1, 1, "native-global", "Global analyzer diagnostic")]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- add an engine-wide diagnostic after real analysis; preserve actual source capture and selected findings.
        python_engine, "analyze", with_global_diagnostic
    )

    report = Standards(tmp_path).analyze(["app.py"], mode=AnalysisMode.RAW, rules=["python:no-secret-in-log"])

    assert report.completion is Completion.COMPLETE
    findings = {item.code: item for item in report.diagnostics}
    selected = findings["SARJ012"]
    assert selected.rule_id == "no-secret-in-log"
    assert selected.help
    global_finding = findings["native-global"]
    assert global_finding.rule_id is None
    assert global_finding.help is None
    assert global_finding.message == "Global analyzer diagnostic"
    assert global_finding.location.path == "app.py"
    assert global_finding.location.position == Position(0, 0, 0)


def test_selected_python_parse_failure_remains_inconclusive(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def broken(:\n", encoding="utf-8")

    report = Standards(tmp_path).analyze(["app.py"], mode=AnalysisMode.RAW, rules=["python:no-secret-in-log"])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert not report.diagnostics
    assert report.issues[0].kind == "analyzer-failure"
    assert "could not be parsed" in report.issues[0].message
