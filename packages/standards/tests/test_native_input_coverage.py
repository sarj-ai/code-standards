from __future__ import annotations

import errno
from pathlib import Path

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.diagnostics import Completion, Conclusion, CoverageDisposition
from sarj_standards.libs.linting import runner


_ENGINES = (
    ("document.sql", "sql:prefer-jsonb", "sarj-sql-lint"),
    ("main.tf", "iac:no-environment-conditional", "sarj-iac-lint"),
)


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
@pytest.mark.parametrize("size", [500_001, 2 * 1024 * 1024], ids=("over-native-limit", "outer-runner-limit"))
@pytest.mark.parametrize("requested", ["file", "directory"])
def test_native_size_rejection_cannot_report_clean_analysis(
    tmp_path: Path, name: str, selector: str, engine: str, size: int, *, requested: str
) -> None:
    source = tmp_path / name
    source.write_bytes(b" " * size)

    report = api.Standards(tmp_path).analyze([name if requested == "file" else "."], rules=[selector])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert not report.diagnostics
    assert [(issue.source, issue.kind) for issue in report.issues] == [(engine, "analyzer-failure")]
    assert "500,000-byte analysis limit" in report.issues[0].message
    assert name in report.issues[0].message
    assert [(tool.name, tool.completion) for tool in report.tools] == [(engine, Completion.FAILED)]


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
def test_native_read_failure_cannot_report_clean_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, selector: str, engine: str
) -> None:
    source = tmp_path / name
    source.write_text("", encoding="utf-8")
    original_read_text = Path.read_text

    def unreadable_text(
        path: Path, encoding: str | None = None, errors: str | None = None, newline: str | None = None
    ) -> str:
        if path == source:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_read_text(path, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- fail the real native filesystem read while preserving Standards routing and normalization.
        Path, "read_text", unreadable_text
    )

    report = api.Standards(tmp_path).analyze([name], rules=[selector])

    assert report.completion is Completion.FAILED
    assert report.conclusion is Conclusion.INCONCLUSIVE
    assert report.exit_code == 2
    assert [(issue.source, issue.kind) for issue in report.issues] == [(engine, "analyzer-failure")]
    assert "PermissionError" in report.issues[0].message
    assert name in report.issues[0].message


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
def test_native_input_failure_preserves_another_engines_findings(
    tmp_path: Path, name: str, selector: str, engine: str
) -> None:
    (tmp_path / name).write_bytes(b" " * 500_001)
    (tmp_path / "service.py").write_text("logger.info('request', token=token)\n", encoding="utf-8")

    report = api.Standards(tmp_path).analyze([name, "service.py"], rules=[selector, "python:no-secret-in-log"])

    assert report.completion is Completion.PARTIAL
    assert report.conclusion is Conclusion.FINDINGS
    assert report.exit_code == 2
    assert [(finding.source, finding.code) for finding in report.diagnostics] == [("sarj-python-lint", "SARJ012")]
    assert [(issue.source, issue.kind) for issue in report.issues] == [(engine, "analyzer-failure")]


@pytest.mark.parametrize("name", ["document.sql", "main.tf"])
def test_legacy_runner_propagates_native_input_rejection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    source = tmp_path / name
    source.write_bytes(b" " * 500_001)

    assert runner.run([str(source)]) == 2
    captured = capsys.readouterr()
    assert "500,000-byte analysis limit" in captured.err
    assert name in captured.err


@pytest.mark.parametrize(("name", "selector", "engine"), _ENGINES)
def test_intentionally_excluded_oversized_input_retains_nonblocking_coverage(
    tmp_path: Path, name: str, selector: str, engine: str
) -> None:
    source = tmp_path / "generated" / name
    source.parent.mkdir()
    source.write_bytes(b" " * 500_001)
    adopted = Manifest(
        version="1.2.3",
        configs=(),
        python_dest=".",
        typescript_dest=".",
        excluded_paths=("generated/**",),
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")

    report = api.Standards(tmp_path).analyze([f"generated/{name}"], rules=[selector])

    assert report.completion is Completion.COMPLETE
    assert report.conclusion is Conclusion.PASSED
    assert report.exit_code == 0
    assert not report.issues
    assert not any(tool.name == engine for tool in report.tools)
    assert [(notice.file_count, notice.disposition) for notice in report.coverage] == [
        (1, CoverageDisposition.EXCLUDED)
    ]
