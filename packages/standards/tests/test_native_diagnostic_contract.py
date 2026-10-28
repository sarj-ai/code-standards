from __future__ import annotations

import codecs
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sarj_iac_lint.rule_base import Diagnostic as IacDiagnostic
from sarj_python_lint.rule_base import Diagnostic as PythonDiagnostic
from sarj_rule_contracts import DefaultLevel, Severity as LegacySeverity, diagnostic_severity
from sarj_sql_lint.rule_base import Diagnostic as SqlDiagnostic

from sarj_standards.libs.diagnostics import Position, Severity
from sarj_standards.libs.linting.analysis import normalize_native


type NativeDiagnostic = PythonDiagnostic | SqlDiagnostic | IacDiagnostic
type AdapterField = str | bool | None


@dataclass(frozen=True, slots=True)
class AdapterDiagnostic:
    path: Path
    col: int = 1
    column_encoding: AdapterField = "codepoints"
    severity: AdapterField = "error"
    line: int = 1
    code: str = "fixture"
    message: str = "A native finding"


@dataclass(frozen=True, slots=True)
class LegacyDiagnostic:
    path: Path
    line: int = 1
    col: int = 1
    code: str = "fixture"
    message: str = "A legacy finding"


@pytest.mark.parametrize("diagnostic_type", [PythonDiagnostic, SqlDiagnostic, IacDiagnostic])
@pytest.mark.parametrize("level", [DefaultLevel.ERROR, DefaultLevel.WARNING])
def test_native_diagnostic_levels_preserve_existing_enum_and_formatting(
    diagnostic_type: type[NativeDiagnostic], level: DefaultLevel
) -> None:
    native = diagnostic_type(Path("source.txt"), 1, 1, "fixture", "finding", severity=diagnostic_severity(level))

    assert LegacySeverity is DefaultLevel
    assert native.severity is level
    assert ("warning: " in native.format()) is (level is DefaultLevel.WARNING)


@pytest.mark.parametrize("diagnostic_type", [PythonDiagnostic, SqlDiagnostic, IacDiagnostic])
@pytest.mark.parametrize("invalid", [DefaultLevel.OFF, "error", "warning", None])
def test_native_diagnostic_replacement_cannot_emit_configuration_or_untyped_levels(
    diagnostic_type: type[NativeDiagnostic], invalid: DefaultLevel | str | None
) -> None:
    native = diagnostic_type(Path("source.txt"), 1, 1, "fixture", "finding")

    with pytest.raises(ValueError, match="diagnostic severity must be error or warning"):
        replace(native, severity=invalid)

    assert native.severity is DefaultLevel.ERROR


@pytest.mark.parametrize("encoding", ["utf8-bytes", "codepoints"])
def test_declared_python_coordinate_domains_preserve_physical_unicode_offsets(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "unicode.py"
    source = 'value = "😀éx"\r\n'
    prefix = source[: source.index("x")]
    raw = codecs.BOM_UTF8 + source.encode("utf-8")
    path.write_bytes(raw)
    column = len(prefix.encode("utf-8")) + 1 if encoding == "utf8-bytes" else len(prefix) + 1
    native = AdapterDiagnostic(path, col=column, column_encoding=encoding)

    diagnostic = normalize_native(native, source="sarj-python-lint", root=tmp_path, metadata={}, documents={})

    assert diagnostic.location.position == Position(
        0, len(prefix.encode("utf-16-le")) // 2, len(codecs.BOM_UTF8) + len(prefix.encode("utf-8"))
    )


@pytest.mark.parametrize("encoding", ["bytes", "utf16", "", None, True])
@pytest.mark.parametrize("available", [False, True])
def test_python_adapter_rejects_unknown_encoding_even_without_source(
    tmp_path: Path, encoding: AdapterField, *, available: bool
) -> None:
    path = tmp_path / "source.py"
    if available:
        path.write_text("value = 1\n", encoding="utf-8")
    native = AdapterDiagnostic(path, column_encoding=encoding)

    with pytest.raises(ValueError, match="column encoding must be utf8-bytes or codepoints"):
        normalize_native(native, source="sarj-python-lint", root=tmp_path, metadata={}, documents={})


@pytest.mark.parametrize("level", ["off", "info", "", None, True])
def test_native_adapter_rejects_unknown_severity_instead_of_promoting_it(tmp_path: Path, level: AdapterField) -> None:
    path = tmp_path / "source.sql"
    path.write_text("SELECT 1;\n", encoding="utf-8")
    native = AdapterDiagnostic(path, severity=level)

    with pytest.raises(ValueError, match="diagnostic severity must be error or warning"):
        normalize_native(native, source="sarj-sql-lint", root=tmp_path, metadata={}, documents={})


def test_legacy_native_adapter_without_optional_severity_keeps_error_default(tmp_path: Path) -> None:
    path = tmp_path / "source.sql"
    path.write_text("SELECT 1;\n", encoding="utf-8")

    diagnostic = normalize_native(
        LegacyDiagnostic(path), source="sarj-sql-lint", root=tmp_path, metadata={}, documents={}
    )

    assert diagnostic.severity is Severity.ERROR
