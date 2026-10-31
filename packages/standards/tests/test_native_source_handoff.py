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
from sarj_standards.libs.linting import textlint
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


@pytest.mark.parametrize(
    ("relative", "raw"),
    [
        ("config.yaml", "prefix: 😀\n# name is build\nname: build\n".encode()),
        ("config.yaml", b"\xef\xbb\xbf" + "prefix: 😀\r\n# name is build\r\nname: build\r\n".encode()),
        ("config.yaml", b"\xef\xbb\xbfprefix: stable\r# name is build\rname: build\r"),
        ("config.toml", b'prefix = "stable"\r\n# name is build\r\nname = "build"\r\n'),
    ],
    ids=("yaml-unicode-lf", "yaml-bom-crlf", "yaml-bom-lone-cr", "toml-crlf"),
)
@pytest.mark.parametrize("delete_after_analysis", [False, True])
@pytest.mark.parametrize("absolute_input", [False, True])
def test_text_analysis_projects_its_captured_revision_and_refreshes_next_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    relative: str,
    raw: bytes,
    delete_after_analysis: bool,
    absolute_input: bool,
) -> None:
    path = tmp_path / relative
    path.write_bytes(raw)
    replacement = b"name: clean\n" if path.suffix == ".yaml" else b'name = "clean"\n'
    reads: list[Path] = []
    captures: list[SourceCatalog] = []
    read = Path.read_bytes
    check = textlint.check_paths

    def counting_read(target: Path) -> bytes:
        if target == path:
            reads.append(target)
        return read(target)

    def complete_then_change(
        paths: Sequence[str],
        *,
        root: Path | None = None,
        rule_ids: frozenset[str] | None = None,
        sources: SourceCatalog | None = None,
    ) -> list[textlint.Finding]:
        result = check(paths, root=root, rule_ids=rule_ids, sources=sources)
        assert sources is not None
        if not captures:
            assert len(result) == 1
        else:
            assert result == []
        snapshot = sources.get(path)
        assert snapshot is not None
        assert snapshot.raw == (raw if not captures else replacement)
        captures.append(sources)
        if delete_after_analysis:
            path.unlink()
        else:
            path.write_bytes(replacement)
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- count physical capture reads; projection must not reopen the selected file.
        Path, "read_bytes", counting_read
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- keep real text findings and change source only after analysis, before projection.
        textlint, "check_paths", complete_then_change
    )
    standards = Standards(tmp_path)
    selected = [str(path) if absolute_input else relative]
    original = standards.analyze(selected, rules=["text:exact-config-comment-restatement"])

    assert original.completion is Completion.COMPLETE
    assert not original.issues
    [finding] = original.diagnostics
    assert finding.code == "SARJ306"
    assert finding.location.path == relative
    assert finding.location.position is not None
    assert finding.location.position.byte_offset == raw.index(b"# name is build")
    assert reads == [path]

    path.write_bytes(replacement)
    changed = standards.analyze(selected, rules=["text:exact-config-comment-restatement"])

    assert changed.completion is Completion.COMPLETE
    assert not changed.issues
    assert not changed.diagnostics
    assert reads == [path, path]
    assert len(captures) == 2
    assert captures[0] is not captures[1]


def test_text_missing_capture_fails_without_projection_disk_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"# name is build\nname: build\n")
    check = textlint.check_paths

    def omit_text_handoff(
        paths: Sequence[str],
        *,
        root: Path | None = None,
        rule_ids: frozenset[str] | None = None,
        sources: SourceCatalog | None = None,
    ) -> list[textlint.Finding]:
        assert sources is not None
        result = check(paths, root=root, rule_ids=rule_ids)
        path.unlink()
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- real findings omit the request capture; projection must fail instead of reading again.
        textlint, "check_paths", omit_text_handoff
    )

    report = Standards(tmp_path).analyze([path.name], rules=["text:exact-config-comment-restatement"])

    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    [issue] = report.issues
    assert issue.kind == "analyzer-failure"
    assert "text diagnostic source was not captured" in issue.message


def test_text_projection_keeps_captured_path_after_symlink_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    raw = b"prefix: stable\n# name is build\nname: build\n"
    path.write_bytes(raw)
    replacement = tmp_path / "replacement.yaml"
    replacement.write_bytes(b"name: clean\n")
    check = textlint.check_paths

    def replace_after_analysis(
        paths: Sequence[str],
        *,
        root: Path | None = None,
        rule_ids: frozenset[str] | None = None,
        sources: SourceCatalog | None = None,
    ) -> list[textlint.Finding]:
        result = check(paths, root=root, rule_ids=rule_ids, sources=sources)
        assert len(result) == 1
        path.unlink()
        path.symlink_to(replacement)
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- replace the real analyzed path only after its findings and bytes are captured.
        textlint, "check_paths", replace_after_analysis
    )

    report = Standards(tmp_path).analyze([path.name], rules=["text:exact-config-comment-restatement"])

    assert report.completion is Completion.COMPLETE
    assert not report.issues
    [finding] = report.diagnostics
    assert finding.location.path == path.name
    assert finding.location.position is not None
    assert finding.location.position.byte_offset == raw.index(b"# name is build")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"# name is build\nname: build\n", 1),
        (b"# sarj-noqa: SARJ306\n# name is build\nname: build\n", 0),
        (b"# Generated by tool; DO NOT EDIT\n# name is build\nname: build\n", 0),
        (b"# name is build\nname: [\n", 0),
        (b"# name is build\nname: \xff\n", 0),
    ],
    ids=("owned", "suppressed", "generated", "malformed-yaml", "invalid-utf8"),
)
def test_text_capture_preserves_standalone_decoding_and_rule_boundaries(
    tmp_path: Path, raw: bytes, expected: int
) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(raw)
    selected = frozenset({"exact-config-comment-restatement"})
    standalone = textlint.check_paths([str(path)], root=tmp_path, rule_ids=selected)
    sources = SourceCatalog()

    shared = textlint.check_paths([str(path)], root=tmp_path, rule_ids=selected, sources=sources)

    assert shared == standalone
    assert len(shared) == expected
    snapshot = sources.get(path)
    assert snapshot is not None
    assert snapshot.raw == raw


@pytest.mark.parametrize("shared", [False, True])
def test_standalone_text_reads_each_occurrence_while_shared_capture_reuses_one_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, shared: bool
) -> None:
    path = tmp_path / "config.yaml"
    original = b"# name is build\nname: build\n"
    replacement = b"name: clean\n"
    path.write_bytes(original)
    reads: list[bytes] = []
    read = Path.read_bytes

    def replace_after_read(target: Path) -> bytes:
        captured = read(target)
        if target == path:
            reads.append(captured)
            path.write_bytes(replacement)
        return captured

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- retain actual reads and replace the file after the selected physical capture.
        Path, "read_bytes", replace_after_read
    )
    findings = textlint.check_paths(
        [str(path), str(path)],
        root=tmp_path,
        rule_ids=frozenset({"exact-config-comment-restatement"}),
        sources=SourceCatalog() if shared else None,
    )

    assert [finding.code for finding in findings] == ["SARJ306"] * (2 if shared else 1)
    assert reads == ([original] if shared else [original, replacement])
