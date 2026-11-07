from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.api import Standards
from sarj_standards.libs.diagnostics import (
    Completion,
    CoverageDisposition,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Fix,
    FixSafety,
    Location,
    Position,
    Region,
    RelatedLocation,
    RuleExecution,
    RuleExecutionState,
    Severity,
    TextEdit,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting import result_cache
from sarj_standards.libs.linting.result_cache import CachedResult, cached_python_analysis


if TYPE_CHECKING:
    from pathlib import Path


def _report(name: str = "sarj-python-lint", *, completion: Completion = Completion.COMPLETE) -> ToolReport:
    start, end = Position(1, 0, 0), Position(1, 4, 4)
    location = Location("app/models.py", region=Region(start, end))
    return ToolReport(
        name,
        completion,
        diagnostics=(
            Diagnostic(
                "SARJ001",
                "message",
                Severity.WARNING,
                name,
                location,
                rule_id="example",
                help="help",
                related=(RelatedLocation("origin", Location("app/other.py")),),
                notes=("note",),
                fixes=(Fix("Replace", FixSafety.SAFE, (TextEdit(location, "text", expected_text_hash="a" * 64),)),),
                tags=("tag",),
                fingerprint="f" * 64,
            ),
        ),
        issues=() if completion is Completion.COMPLETE else (ExecutionIssue(name, "analyzer-failure", "failed"),),
        version="1.0.0",
        duration_ms=12,
        file_count=2,
        rule_executions=(RuleExecution("example", RuleExecutionState.RAN, 2, requires_type_information=False),),
    )


@pytest.fixture
def cached_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repository"
    (root / "app").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n')
    (root / "app" / "models.py").write_text("value = 1\n")
    (root / "README.md").write_text("docs\n")
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE_WRITE", "1")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- editable test installs have no immutable engine record.
        result_cache, "_engine_identity", lambda: "engine"
    )
    return root


def _analyze(
    root: Path, calls: list[str], report: ToolReport | None = None, selected: tuple[str, ...] = ("app/models.py",)
) -> CachedResult:
    def compute() -> CachedResult:
        calls.append("ran")
        return CachedResult((report or _report(),), (CoverageNotice("sqlfluff", "unsupported", 1),))

    return cached_python_analysis("sarj-python-lint", root, selected=selected, parameters=("rules=*",), compute=compute)


def test_cached_result_round_trips_every_report_field() -> None:
    result = CachedResult((_report(),), (CoverageNotice("sqlfluff", "unsupported", 1, CoverageDisposition.FAILED),))
    encoded = parse_unique_json(json.dumps(result_cache.encode_result(result)))
    assert result_cache.decode_result(encoded) == result


def test_unchanged_python_inputs_reuse_the_complete_result(cached_repository: Path) -> None:
    calls: list[str] = []
    first = _analyze(cached_repository, calls)
    (cached_repository / "README.md").write_text("changed documentation\n")
    (cached_repository / "notes.txt").write_text("a new non-Python file\n")
    assert _analyze(cached_repository, calls) == first
    assert calls == ["ran"]


@pytest.mark.parametrize(
    "change",
    [
        "python-content",
        "configuration",
        "new-directory",
        "codegen-marker",
        "codegen-marker-directory",
        "selected-order",
    ],
)
def test_any_python_input_change_runs_the_analyzer(cached_repository: Path, change: str) -> None:
    calls: list[str] = []
    _analyze(cached_repository, calls)
    match change:
        case "python-content":
            (cached_repository / "app" / "models.py").write_text("value = 2\n")
        case "configuration":
            (cached_repository / "pyproject.toml").write_text('[project]\nname = "renamed"\nversion = "0.1.0"\n')
        case "new-directory":
            (cached_repository / "app" / "namespace").mkdir()
        case "codegen-marker":
            (cached_repository / "app" / "codegen.yml").write_text("generator: example\n")
        case "codegen-marker-directory":
            (cached_repository / "app" / ".openapi-generator").mkdir()
        case _:
            (cached_repository / "app" / "later.py").write_text("value = 1\n")
            _analyze(cached_repository, calls, selected=("app/later.py", "app/models.py"))
            calls.clear()
            _analyze(cached_repository, calls, selected=("app/models.py", "app/later.py"))
            assert calls == ["ran"]
            return
    _analyze(cached_repository, calls)
    assert calls == ["ran", "ran"]


def test_failed_results_are_never_stored(cached_repository: Path) -> None:
    calls: list[str] = []
    _analyze(cached_repository, calls, _report(completion=Completion.FAILED))
    _analyze(cached_repository, calls)
    assert calls == ["ran", "ran"]


def test_read_only_runs_never_write(cached_repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SARJ_STANDARDS_RESULT_CACHE_WRITE")
    calls: list[str] = []
    _analyze(cached_repository, calls)
    _analyze(cached_repository, calls)
    assert calls == ["ran", "ran"]


@pytest.mark.parametrize("payload", ["not json", "{}", '{"schema": 1}', "[]"])
def test_invalid_entries_run_the_analyzer(cached_repository: Path, payload: str) -> None:
    calls: list[str] = []
    _analyze(cached_repository, calls)
    cache = cached_repository.parent / "cache"
    [entry] = cache.glob("v1/sarj-python-lint/*.json")
    entry.write_text(payload)
    _analyze(cached_repository, calls)
    assert calls == ["ran", "ran"]


@pytest.mark.parametrize("value", ["", "off", "0"])
def test_kill_switch_disables_the_cache(cached_repository: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE", value)
    calls: list[str] = []
    _analyze(cached_repository, calls)
    _analyze(cached_repository, calls)
    assert calls == ["ran", "ran"]
    assert not (cached_repository.parent / "cache").exists()


def test_unavailable_engine_identity_runs_the_analyzer(
    cached_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def editable() -> str:
        msg = "code-standards has no immutable installed record"
        raise ValueError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- editable installs cannot prove engine identity.
        result_cache, "_engine_identity", editable
    )
    calls: list[str] = []
    _analyze(cached_repository, calls)
    _analyze(cached_repository, calls)
    assert calls == ["ran", "ran"]
    assert not (cached_repository.parent / "cache").exists()


@pytest.mark.parametrize(
    ("direct_url", "editable"),
    [
        (None, False),
        ('{"url": "file:///wheel.whl", "archive_info": {}}', False),
        ('{"url": "file:///src", "dir_info": {}}', False),
        ('{"url": "file:///src", "dir_info": {"editable": true}}', True),
    ],
)
def test_editable_distributions_are_detected(direct_url: str | None, editable: bool) -> None:
    assert result_cache.editable_distribution(direct_url) is editable


def test_cached_native_python_report_is_identical(cached_repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (cached_repository / "app" / "test_service.py").write_text("from unittest.mock import Mock\nfake = Mock()\n")
    first = Standards(cached_repository).analyze(["app/test_service.py"], rules=["python:mock-without-spec"])
    cache = cached_repository.parent / "cache"
    assert list(cache.glob("v1/sarj-python-lint/*.json"))
    second = Standards(cached_repository).analyze(["app/test_service.py"], rules=["python:mock-without-spec"])
    assert second == first
    assert first.diagnostics
    assert "sarj-python-lint reused" in capsys.readouterr().err
