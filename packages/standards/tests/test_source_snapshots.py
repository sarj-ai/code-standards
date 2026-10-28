from __future__ import annotations

import codecs
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from sarj_python_lint.__main__ import analyze as analyze_python
from sarj_rule_contracts import SourceSnapshot

from sarj_standards.libs.diagnostics import Position, SourceDocument
from sarj_standards.libs.linting.analysis import PythonSourceDocument, normalize_native


if TYPE_CHECKING:
    from pathlib import Path


def test_physical_document_uses_captured_bytes_after_replacement_or_deletion(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    raw = codecs.BOM_UTF8 + "name = '😀'\r\n".encode() + b"legacy = '\xff'\rtoken = 1\n"
    path.write_bytes(raw)
    snapshot = SourceSnapshot.read(path)
    path.write_bytes(b"changed = 1\n")

    document = SourceDocument.from_snapshot(snapshot)
    start = raw.index(b"token")
    region = document.region(start_byte=start, end_byte=start + len(b"token"))

    assert document.text.encode("utf-8", "surrogateescape") == raw
    assert (region.start.line, region.start.character, region.start.byte_offset) == (2, 0, start)
    assert raw[region.start.byte_offset : region.end.byte_offset] == b"token"
    assert SourceDocument.read(path).text == "changed = 1\n"
    path.unlink()
    assert SourceDocument.from_snapshot(snapshot).text == document.text


def test_source_document_equality_survives_independent_coordinate_queries(tmp_path: Path) -> None:
    snapshot = SourceSnapshot(tmp_path / "unicode.py", "A😀B\r\n".encode())
    left = SourceDocument.from_snapshot(snapshot)
    right = SourceDocument.from_snapshot(snapshot)
    expected = Position(0, 3, 5)

    assert left == right
    assert left.utf16_point(line=0, character=3) == expected
    assert right.point(line=1, column=3) == expected
    assert left == right
    assert right.byte_point(line=1, column=6) == expected
    assert left == right
    assert right.utf16_point(line=0, character=3) == expected
    assert left == right


def test_rejected_surrogate_query_preserves_source_document_equality(tmp_path: Path) -> None:
    snapshot = SourceSnapshot(tmp_path / "legacy.py", b"A\xff" + "😀B\r\n".encode())
    left = SourceDocument.from_snapshot(snapshot)
    right = SourceDocument.from_snapshot(snapshot)

    assert left == right
    assert left.utf16_point(line=0, character=3) is None
    assert left == right
    assert left.utf16_point(line=0, character=4) == Position(0, 4, 6)
    assert right.byte_point(line=1, column=7) == Position(0, 4, 6)
    assert left == right
    assert left.text.encode("utf-8", errors="surrogateescape") == snapshot.raw


def test_ascii_coordinate_query_keeps_equal_source_documents(tmp_path: Path) -> None:
    left = SourceDocument(tmp_path / "ascii.py", "plain\r\n")
    right = SourceDocument(tmp_path / "ascii.py", "plain\r\n")

    assert left.utf16_point(line=0, character=2) == Position(0, 2, 2)
    assert left == right


def test_source_document_equality_still_distinguishes_path_text_and_newlines(tmp_path: Path) -> None:
    path = tmp_path / "unicode.py"
    document = SourceDocument(path, "A😀B\r\n")

    assert document.utf16_point(line=0, character=3) == Position(0, 3, 5)
    assert document != SourceDocument(tmp_path / "other.py", "A😀B\r\n")
    assert document != SourceDocument(path, "A😀C\r\n")
    assert document != SourceDocument(path, "A😀B\n")


def test_source_document_cache_equality_preserves_mutable_value_api(tmp_path: Path) -> None:
    document = SourceDocument(tmp_path / "unicode.py", "A😀B\r\n")
    assert document.utf16_point(line=0, character=3) == Position(0, 3, 5)

    copied = replace(document)
    assert copied == document
    with pytest.raises(TypeError, match="unhashable"):
        hash(document)

    relocated = tmp_path / "relocated.py"
    document.path = relocated
    assert document.path == relocated
    assert document == SourceDocument(relocated, "A😀B\r\n")
    assert document.utf16_point(line=0, character=3) == Position(0, 3, 5)


@pytest.mark.parametrize(
    "raw",
    [
        "from unittest.mock import Mock\r\nvalue = '😀'; fake = Mock()\r\n".encode(),
        codecs.BOM_UTF8 + "from unittest.mock import Mock\rvalue = '😀'; fake = Mock()\r".encode(),
        "# coding: latin-1\r\nfrom unittest.mock import Mock\r\nvalue = 'café'; fake = Mock()\r\n".encode("latin-1"),
        "# coding: cp1252\nfrom unittest.mock import Mock\nvalue = '€'; fake = Mock()\n".encode("cp1252"),
    ],
    ids=("astral-crlf", "bom-lone-cr", "latin1-cookie-crlf", "cp1252-cookie"),
)
def test_native_normalization_can_keep_the_analyzed_revision_from_captured_bytes(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "test_service.py"
    path.write_bytes(raw)
    snapshot = SourceSnapshot.read(path)
    [finding] = analyze_python(["mock-without-spec"], [path])
    document = PythonSourceDocument.from_snapshot(snapshot)
    path.write_text("changed = 1\n")

    normalized = normalize_native(
        finding,
        source="sarj-python-lint",
        root=tmp_path,
        metadata={},
        documents={path.resolve(): document},
    )

    position = normalized.location.position
    assert position is not None
    assert position.byte_offset == raw.index(b"Mock()")
    assert normalized.code == finding.code
    assert document.raw == raw
    assert PythonSourceDocument.read(path).raw == b"changed = 1\n"
    path.unlink()
    assert PythonSourceDocument.from_snapshot(snapshot).raw == raw
