from __future__ import annotations

import codecs
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from jsonschema import Draft202012Validator, ValidationError
import pytest
from sarj_python_lint import python_source_hash
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic as NativeDiagnostic,
    Fix as NativeFix,
    TextEdit as NativeTextEdit,
)

from sarj_standards.libs.diagnostics import (
    ANALYSIS_SCHEMA,
    AnalysisReport,
    Completion,
    Conclusion,
    Diagnostic,
    Fix,
    FixSafety,
    Location,
    Position,
    Region,
    Severity,
    TextEdit,
    ToolReport,
    to_json,
)
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import analysis
from sarj_standards.libs.linting.analysis import PythonSourceDocument, normalize_native


if TYPE_CHECKING:
    from jsonschema.protocols import Validator
    from pydantic import JsonValue


class _HexDigest(Protocol):
    def hexdigest(self) -> str: ...


_RAW = b"name = 'value'\n"
_DIGEST = sha256(_RAW).hexdigest()
_SLICE_DIGEST = sha256(b"value").hexdigest()
_OLD_SCHEMA_SHA256 = "622d89156b288be9cdb07e6a68e453f7a5faf619f83410a2758004b59547b2ff"


def test_source_hash_is_keyword_only_and_preserves_legacy_edit_values() -> None:
    location = Location("case.py", region=Region(Position(0, 8, 8), Position(0, 13, 13)))
    legacy = TextEdit(location, "updated", _SLICE_DIGEST)
    explicit = TextEdit(location, "updated", _SLICE_DIGEST, expected_source_hash=None)

    assert TextEdit.__match_args__ == ("location", "replacement", "expected_text_hash")
    assert legacy == explicit
    assert legacy.expected_source_hash is None
    enriched = replace(legacy, expected_source_hash=_DIGEST)
    assert enriched.expected_source_hash == _DIGEST
    assert enriched.expected_text_hash == legacy.expected_text_hash
    assert replace(enriched) == enriched
    with pytest.raises(TypeError):
        TextEdit(location, "updated", _SLICE_DIGEST, _DIGEST)  # pyright: ignore[reportCallIssue] -- A fourth positional argument must remain a runtime error.


@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, 1, True])
def test_source_hash_rejects_invalid_digest_values(digest: str | int) -> None:
    location = Location("case.py", region=Region(Position(0, 0, 0), Position(0, 0, 0)))

    with pytest.raises(ValueError, match="expected source hash"):
        TextEdit(location, "", expected_source_hash=digest)  # pyright: ignore[reportArgumentType] -- Runtime validation must reject non-string public inputs.


def test_every_serialization_owner_defaults_to_the_old_wire_shape(tmp_path: Path) -> None:
    report = _report(tmp_path, source_hash=_DIGEST)
    diagnostic = report.diagnostics[0]
    fix = diagnostic.fixes[0]
    edit = fix.edits[0]
    legacy = _report(tmp_path, source_hash=None)

    assert edit.as_dict() == legacy.diagnostics[0].fixes[0].edits[0].as_dict()
    assert fix.as_dict() == legacy.diagnostics[0].fixes[0].as_dict()
    assert diagnostic.as_dict() == legacy.diagnostics[0].as_dict()
    assert report.as_dict() == legacy.as_dict()
    assert to_json(report) == to_json(legacy)
    assert to_json(report, indent=None) == to_json(legacy, indent=None)
    assert "expectedSourceHash" not in to_json(report)
    assert edit.as_dict(include_fix_source_hashes=True).get("expectedSourceHash") == _DIGEST
    assert fix.as_dict(include_fix_source_hashes=True)["edits"][0].get("expectedSourceHash") == _DIGEST
    serialized_fix = diagnostic.as_dict(include_fix_source_hashes=True).get("fixes", [])[0]
    assert serialized_fix["edits"][0].get("expectedSourceHash") == _DIGEST
    serialized_diagnostic = report.as_dict(include_fix_source_hashes=True)["diagnostics"][0]
    assert serialized_diagnostic.get("fixes", [])[0]["edits"][0].get("expectedSourceHash") == _DIGEST
    assert "expectedSourceHash" not in to_json(legacy, include_fix_source_hashes=True)
    assert (
        to_json(report, indent=None, include_fix_source_hashes=True)
        == json.dumps(report.as_dict(include_fix_source_hashes=True), indent=None, sort_keys=True) + "\n"
    )


@pytest.mark.parametrize("invalid", ["true", "false", 0, 1, None])
def test_serialization_requires_an_actual_boolean_even_without_fixes(tmp_path: Path, invalid: str | int | None) -> None:
    report = _report(tmp_path, source_hash=None)
    diagnostic = report.diagnostics[0]
    fix = diagnostic.fixes[0]
    edit = fix.edits[0]
    for serialize in (edit.as_dict, fix.as_dict, diagnostic.as_dict, report.as_dict):
        with pytest.raises(TypeError, match="include fix source hashes"):
            serialize(include_fix_source_hashes=invalid)  # pyright: ignore[reportArgumentType] -- Each callable public boundary must reject truthy or falsey non-boolean values.
    with pytest.raises(TypeError, match="include fix source hashes"):
        to_json(report, include_fix_source_hashes=invalid)  # pyright: ignore[reportArgumentType] -- The exported JSON boundary must preserve strict opt-in semantics.
    empty = AnalysisReport(tmp_path, Completion.COMPLETE, Conclusion.PASSED, ())
    with pytest.raises(TypeError, match="include fix source hashes"):
        empty.as_dict(include_fix_source_hashes=invalid)  # pyright: ignore[reportArgumentType] -- Empty reports must validate the option without depending on an edit being present.


def test_opted_in_wire_requires_updated_schema_and_default_remains_legacy_compatible(tmp_path: Path) -> None:
    report = _report(tmp_path, source_hash=_DIGEST)
    old_schema_path = Path(__file__).with_name("fixtures") / "analysis-v1-before-source-hashes.json"
    assert sha256(old_schema_path.read_bytes()).hexdigest() == _OLD_SCHEMA_SHA256
    old_schema = parse_json(old_schema_path.read_text())
    updated_schema = parse_json(ANALYSIS_SCHEMA.read_text())
    legacy_payload = parse_json(to_json(report))
    enriched_payload = parse_json(to_json(report, include_fix_source_hashes=True))
    assert isinstance(old_schema, dict)
    assert isinstance(updated_schema, dict)
    assert isinstance(legacy_payload, dict)
    assert isinstance(enriched_payload, dict)

    _schema_validator(old_schema).validate(legacy_payload)
    _schema_validator(updated_schema).validate(legacy_payload)
    _schema_validator(updated_schema).validate(enriched_payload)
    with pytest.raises(ValidationError, match="expectedSourceHash"):
        _schema_validator(old_schema).validate(enriched_payload)


def _schema_validator(schema: dict[str, JsonValue]) -> Validator:
    return Draft202012Validator(schema)


@pytest.mark.parametrize(
    "raw",
    [_RAW, codecs.BOM_UTF8 + _RAW, _RAW.replace(b"\n", b"\r\n"), _RAW + b"# unrelated revision\n"],
    ids=("lf", "bom", "crlf", "unrelated-bytes"),
)
def test_real_native_insertion_boundary_preserves_whole_captured_source_provenance(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "case.py"
    path.write_bytes(raw)
    document = PythonSourceDocument.read(path)
    native = NativeDiagnostic(
        path,
        1,
        1,
        "fixture",
        "Adapter insertion boundary",
        fixes=(
            NativeFix("Insert prefix", AutofixPolicy.SAFE, document.source_hash, (NativeTextEdit(1, 1, 1, 1, "# "),)),
        ),
    )
    path.write_bytes(b"concurrently replaced source\n")

    diagnostic = normalize_native(
        native, source="sarj-python-lint", root=tmp_path, metadata={}, documents={path.resolve(): document}
    )

    [fix] = diagnostic.fixes
    [edit] = fix.edits
    assert edit.expected_source_hash == sha256(raw).hexdigest()
    assert edit.expected_text_hash == sha256(b"").hexdigest()
    assert edit.location.region is not None
    assert edit.location.region.start.byte_offset == (3 if raw.startswith(codecs.BOM_UTF8) else 0)
    assert edit.location.region.start == edit.location.region.end
    assert document.source_hash == python_source_hash(raw.decode(document.encoding))
    if raw in {codecs.BOM_UTF8 + _RAW, _RAW.replace(b"\n", b"\r\n")}:
        assert document.source_hash == python_source_hash(_RAW.decode())
        assert edit.expected_source_hash != document.source_hash
    assert path.read_bytes() == b"concurrently replaced source\n"


def test_real_native_latin1_insertion_hashes_physical_bytes_and_keeps_native_guard(tmp_path: Path) -> None:
    raw = b"# coding: latin-1\r\nname = '\xe9'\r\n"
    path = tmp_path / "case.py"
    path.write_bytes(raw)
    document = PythonSourceDocument.read(path)
    native_fix = NativeFix(
        "Insert prefix", AutofixPolicy.SAFE, document.source_hash, (NativeTextEdit(2, 1, 2, 1, "# "),)
    )
    native = NativeDiagnostic(path, 2, 1, "fixture", "Adapter latin-1 boundary", fixes=(native_fix,))

    diagnostic = normalize_native(native, source="sarj-python-lint", root=tmp_path, metadata={}, documents={})

    [edit] = diagnostic.fixes[0].edits
    assert edit.expected_source_hash == sha256(raw).hexdigest()
    assert edit.expected_source_hash != document.source_hash
    assert edit.expected_text_hash == sha256(b"").hexdigest()
    assert edit.location.region is not None
    assert edit.location.region.start.byte_offset == raw.index(b"name")
    stale = replace(native, fixes=(replace(native_fix, source_hash="0" * 64),))
    assert normalize_native(stale, source="sarj-python-lint", root=tmp_path, metadata={}, documents={}).fixes == ()
    assert path.read_bytes() == raw


def test_raw_digest_cache_is_derived_lazy_and_does_not_change_document_equality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hashed: list[bytes] = []

    def observe_digest(raw: bytes) -> _HexDigest:
        hashed.append(raw)
        return sha256(raw)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Observe the actual whole-source hash boundary while retaining the real SHA-256 implementation.
        analysis, "sha256", observe_digest
    )
    path = tmp_path / "case.py"
    path.write_bytes(_RAW)
    left = PythonSourceDocument.read(path)
    right = PythonSourceDocument.read(path)

    assert PythonSourceDocument.__match_args__ == ("document", "raw", "encoding", "utf8_source", "source_hash")
    assert left == right
    assert hashed == []
    before = repr(left)
    assert left.raw_source_hash == _DIGEST
    assert left == right
    assert repr(left) == before
    assert left.raw_source_hash == _DIGEST
    assert hashed == [_RAW]
    assert replace(left, raw=_RAW + b"# changed\n").raw_source_hash == sha256(_RAW + b"# changed\n").hexdigest()
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(left, _raw_source_hash="0" * 64)


@pytest.mark.parametrize(
    "digests", [(None, None), (_DIGEST, None), (None, _DIGEST), (_DIGEST, _DIGEST), (_DIGEST, None, _DIGEST)]
)
def test_fix_accepts_partial_or_matching_source_provenance_for_one_path(digests: tuple[str | None, ...]) -> None:
    edits = _source_edits(digests)

    fix = Fix("Batch edits", FixSafety.SAFE, edits)

    assert fix.edits == edits


@pytest.mark.parametrize("with_unproven_middle", [False, True])
def test_fix_rejects_conflicting_known_source_revisions_for_one_path(*, with_unproven_middle: bool) -> None:
    other_digest = sha256(_RAW + b"# other revision\n").hexdigest()
    digests = (_DIGEST, None, other_digest) if with_unproven_middle else (_DIGEST, other_digest)
    edits = _source_edits(digests)

    with pytest.raises(ValueError, match="same source revision"):
        Fix("Contradictory batch", FixSafety.SAFE, edits)


def test_fix_keeps_distinct_source_revisions_for_different_logical_paths() -> None:
    [first] = _source_edits((_DIGEST,))
    second = replace(
        first,
        location=replace(first.location, path="other.py"),
        expected_source_hash=sha256(b"other source\n").hexdigest(),
    )
    fix = Fix("Multi-file batch", FixSafety.SAFE, (first, second))
    legacy = Fix(
        "Multi-file batch", FixSafety.SAFE, tuple(replace(edit, expected_source_hash=None) for edit in fix.edits)
    )

    assert fix.edits == (first, second)
    assert fix.as_dict() == legacy.as_dict()
    assert [edit.get("expectedSourceHash") for edit in fix.as_dict(include_fix_source_hashes=True)["edits"]] == [
        first.expected_source_hash,
        second.expected_source_hash,
    ]


def _report(root: Path, *, source_hash: str | None) -> AnalysisReport:
    location = Location("case.py", region=Region(Position(0, 8, 8), Position(0, 13, 13)))
    edit = TextEdit(location, "updated", _SLICE_DIGEST, expected_source_hash=source_hash)
    fix = Fix("Rename value", FixSafety.SAFE, (edit,))
    diagnostic = Diagnostic("fixture", "Suggested edit", Severity.WARNING, "fixture", location, fixes=(fix,))
    return AnalysisReport(
        root, Completion.COMPLETE, Conclusion.FINDINGS, (ToolReport("fixture", Completion.COMPLETE, (diagnostic,)),)
    )


def _source_edits(digests: tuple[str | None, ...]) -> tuple[TextEdit, ...]:
    return tuple(
        TextEdit(
            Location("case.py", region=Region(Position(0, index, index), Position(0, index + 1, index + 1))),
            "updated",
            expected_source_hash=digest,
        )
        for index, digest in enumerate(digests)
    )
