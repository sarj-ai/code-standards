from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sarj_iac_lint.__main__ as iac_engine
import sarj_python_lint.__main__ as python_engine
from sarj_rule_contracts import SourceCatalog
import sarj_sql_lint.__main__ as sql_engine
from sarj_sql_lint.rule_base import Diagnostic as SqlDiagnostic

from sarj_standards.api import Standards
from sarj_standards.libs.diagnostics import Completion, SourceDocument
from sarj_standards.libs.linting.analysis import PythonSourceDocument, normalize_native


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sarj_iac_lint.rule_base import Diagnostic as IacDiagnostic
    from sarj_python_lint.rule_base import Diagnostic as PythonDiagnostic


_SOURCES = (
    (
        "python",
        "test_service.py",
        "python:mock-without-spec",
        "SARJ040",
        "from unittest.mock import Mock\r\nvalue = '😀'; fake = Mock()\r\n".encode(),
        b"Mock()",
        b"value = 1\n",
    ),
    (
        "sql",
        "supabase/migrations/001_document.sql",
        "sql:prefer-jsonb",
        "SARJ106",
        'CREATE TABLE document ("😀" text, metadata json);\r\n'.encode(),
        b"json",
        b"SELECT 1;\n",
    ),
    (
        "iac",
        "main.tf",
        "iac:no-environment-conditional",
        "SARJ204",
        '# 😀\r\nlocals {\r\n  redis_tier = var.environment == "prod" ? "STANDARD_HA" : "BASIC"\r\n}\r\n'.encode(),
        b"redis_tier",
        b"locals { redis_tier = var.redis_tier }\n",
    ),
)


def _observe_completion(
    monkeypatch: pytest.MonkeyPatch, engine: str, completed: Callable[[SourceCatalog | None], None]
) -> None:
    match engine:
        case "python":
            original_python = python_engine.analyze

            def analyze_python(
                rule_ids: Sequence[str],
                paths: list[Path],
                *,
                baseline: Path | None = None,
                root: Path | None = None,
                jobs: int = 1,
                sources: SourceCatalog | None = None,
            ) -> list[PythonDiagnostic]:
                result = original_python(rule_ids, paths, baseline=baseline, root=root, jobs=jobs, sources=sources)
                completed(sources)
                return result

            monkeypatch.setattr(  # sarj-noqa: SARJ445 -- forward actual analysis and edit only after it completes, before normalization.
                python_engine, "analyze", analyze_python
            )
        case "sql":
            original_sql = sql_engine.analyze

            def analyze_sql(
                rule_ids: Sequence[str], paths: list[Path], *, sources: SourceCatalog | None = None
            ) -> list[SqlDiagnostic]:
                result = original_sql(rule_ids, paths, sources=sources)
                completed(sources)
                return result

            monkeypatch.setattr(  # sarj-noqa: SARJ445 -- preserve real SQL diagnostics while observing the source handoff boundary.
                sql_engine, "analyze", analyze_sql
            )
        case _:
            original_iac = iac_engine.analyze

            def analyze_iac(
                rule_ids: Sequence[str], paths: list[Path], *, sources: SourceCatalog | None = None
            ) -> list[IacDiagnostic]:
                result = original_iac(rule_ids, paths, sources=sources)
                completed(sources)
                return result

            monkeypatch.setattr(  # sarj-noqa: SARJ445 -- preserve actual IaC decoding and findings before changing the file revision.
                iac_engine, "analyze", analyze_iac
            )


@pytest.mark.parametrize(("engine", "relative", "selector", "code", "raw", "token", "replacement"), _SOURCES)
@pytest.mark.parametrize("absolute_input", [False, True])
def test_ordinary_standards_analysis_normalizes_the_captured_revision_and_refreshes_next_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: str,
    relative: str,
    selector: str,
    code: str,
    raw: bytes,
    token: bytes,
    replacement: bytes,
    absolute_input: bool,
) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    captures: list[SourceCatalog] = []
    reads: list[Path] = []
    read = Path.read_bytes

    def counting_read(target: Path) -> bytes:
        if target == path:
            reads.append(target)
        return read(target)

    def completed(sources: SourceCatalog | None) -> None:
        assert sources is not None
        snapshot = sources.get(path)
        assert snapshot is not None
        assert snapshot.raw == (raw if not captures else replacement)
        captures.append(sources)
        path.write_bytes(replacement)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count actual selected-source capture reads and detect any normalizer reread.
        Path, "read_bytes", counting_read
    )
    _observe_completion(monkeypatch, engine, completed)
    standards = Standards(tmp_path)
    selected = [str(path) if absolute_input else relative]

    original = standards.analyze(selected, rules=[selector])

    assert original.completion is Completion.COMPLETE
    assert not original.issues
    [finding] = original.diagnostics
    assert finding.code == code
    assert finding.location.path == relative
    assert finding.location.position is not None
    assert finding.location.position.byte_offset == raw.index(token)
    assert reads == [path]

    changed = standards.analyze(selected, rules=[selector])

    assert changed.completion is Completion.COMPLETE
    assert not changed.issues
    assert not changed.diagnostics
    assert reads == [path, path]
    assert len(captures) == 2
    assert captures[0] is not captures[1]


def test_all_native_tools_share_one_request_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalogs: list[SourceCatalog] = []
    paths: list[str] = []
    selectors: list[str] = []
    for engine, relative, selector, _code, raw, _token, _replacement in _SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        paths.append(relative)
        selectors.append(selector)

        def completed(sources: SourceCatalog | None) -> None:
            assert sources is not None
            catalogs.append(sources)

        _observe_completion(monkeypatch, engine, completed)

    report = Standards(tmp_path).analyze(paths, rules=selectors)

    assert not report.issues
    assert len(report.diagnostics) == 3
    assert len(catalogs) == 3
    assert catalogs[0] is catalogs[1] is catalogs[2]


def test_missing_captured_source_fails_without_normalizer_disk_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "test_service.py"
    path.write_text("from unittest.mock import Mock\nfake = Mock()\n")
    original = python_engine.analyze

    def omit_source_handoff(
        rule_ids: Sequence[str],
        paths: list[Path],
        *,
        baseline: Path | None = None,
        root: Path | None = None,
        sources: SourceCatalog | None = None,
    ) -> list[PythonDiagnostic]:
        assert sources is not None
        result = original(rule_ids, paths, baseline=baseline, root=root)
        path.unlink()
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise a missing handoff using real diagnostics; no source may be reread as a substitute.
        python_engine, "analyze", omit_source_handoff
    )

    report = Standards(tmp_path).analyze([path.name], rules=["python:mock-without-spec"])

    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    [issue] = report.issues
    assert issue.kind == "analyzer-failure"
    assert "native diagnostic source was not captured" in issue.message


def test_normalization_keeps_exact_capture_keys_when_paths_resolve_to_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "source.sql"
    (tmp_path / "nested").mkdir()
    alias = tmp_path / "nested" / ".." / path.name
    sources = SourceCatalog()
    path.write_text("é token\n")
    sources.capture(path)
    path.write_text("😀 token\n")
    sources.capture(alias)
    documents: dict[Path, SourceDocument | PythonSourceDocument | None] = {}

    original = normalize_native(
        SqlDiagnostic(path, 1, 3, "fixture", "first capture"),
        source="sarj-sql-lint",
        root=tmp_path,
        metadata={},
        documents=documents,
        sources=sources,
    )
    replacement = normalize_native(
        SqlDiagnostic(alias, 1, 3, "fixture", "second capture"),
        source="sarj-sql-lint",
        root=tmp_path,
        metadata={},
        documents=documents,
        sources=sources,
    )

    assert original.location.path == replacement.location.path == path.name
    assert original.location.position is not None
    assert replacement.location.position is not None
    assert original.location.position.byte_offset == len("é ".encode())
    assert replacement.location.position.byte_offset == len("😀 ".encode())


@pytest.mark.parametrize(
    ("engine", "relative", "selector", "raw", "token"),
    [
        (
            "sql",
            "supabase/migrations/001_document.sql",
            "sql:prefer-jsonb",
            b'CREATE TABLE document ("\xe1\x80(" text, metadata json);\r\n',
            b"json",
        ),
        (
            "iac",
            "main.tf",
            "iac:no-environment-conditional",
            b'locals { /* \xe1\x80( */ redis_tier = var.environment == "prod" ? "HA" : "BASIC" }\r\n',
            b"redis_tier",
        ),
    ],
)
@pytest.mark.parametrize("valid_utf8", [False, True])
def test_replacement_decoding_keeps_findings_without_inventing_physical_positions(
    tmp_path: Path,
    *,
    engine: str,
    relative: str,
    selector: str,
    raw: bytes,
    token: bytes,
    valid_utf8: bool,
) -> None:
    if valid_utf8:
        raw = raw.replace(b"\xe1\x80(", "�(".encode())
    else:
        prefix = raw[: raw.index(token)]
        assert len(prefix.decode("utf-8", "replace")) != len(prefix.decode("utf-8", "surrogateescape"))
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    rule = selector.partition(":")[2]
    legacy = sql_engine.analyze([rule], [path]) if engine == "sql" else iac_engine.analyze([rule], [path])
    assert len(legacy) == 1

    report = Standards(tmp_path).analyze([relative], rules=[selector])

    assert report.completion is Completion.COMPLETE
    assert not report.issues
    [finding] = report.diagnostics
    assert finding.code == legacy[0].code
    fallback = normalize_native(legacy[0], source=f"sarj-{engine}-lint", root=tmp_path, metadata={}, documents={})
    if valid_utf8:
        assert finding.location.position is not None
        assert finding.location.position.byte_offset == raw.index(token)
        assert fallback.location.position == finding.location.position
    else:
        assert finding.location.position is None
        assert fallback.location.position is None
