from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import analyze, deduplicate_diagnostics, main
from sarj_python_lint.rule_base import Diagnostic, Severity


if TYPE_CHECKING:
    import pytest


def _diagnostic(code: str, *, line: int = 3) -> Diagnostic:
    return Diagnostic(Path("service.py"), line, 5, code, code)


def test_specific_test_docstring_finding_suppresses_generic_restatements() -> None:
    diagnostics = [_diagnostic("SARJ050"), _diagnostic("SARJ085"), _diagnostic("SARJ088")]

    assert [finding.code for finding in deduplicate_diagnostics(diagnostics)] == ["SARJ088"]


def test_typed_section_finding_suppresses_per_section_twins() -> None:
    diagnostics = [_diagnostic("SARJ086"), _diagnostic("SARJ087"), _diagnostic("SARJ092")]

    assert [finding.code for finding in deduplicate_diagnostics(diagnostics)] == ["SARJ092"]


def test_typed_section_precedence_uses_the_owning_docstring_across_lines(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def decode(value: str) -> str:\n"
        '    """Decode a value.\n\n'
        "    Args:\n"
        "        value (str): Value to decode.\n"
        '    """\n'
        "    return value\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["docstring-args-restate-signature", "no-docstring-type-restatement"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ086"]
    assert diagnostics[0].severity is Severity.ERROR
    assert diagnostics[0].line == 2


def test_typed_return_precedence_uses_the_owning_docstring_across_lines(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def decode(value: str) -> str:\n"
        '    """Produce the wire representation.\n\n'
        "    Returns:\n"
        "        str\n"
        '    """\n'
        "    return value\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["docstring-returns-restate-signature", "no-docstring-type-restatement"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ087"]
    assert diagnostics[0].severity is Severity.ERROR
    assert diagnostics[0].line == 2


def test_owner_precedence_never_crosses_docstrings(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def decode(value: str) -> str:\n"
        '    """Decode a value.\n\n'
        "    Args:\n"
        "        value (str): Value to decode.\n"
        '    """\n'
        "    return value\n\n"
        "def encode(value: str) -> str:\n"
        '    """Encode a value.\n\n'
        "    Args:\n"
        "        value: Value to encode.\n"
        '    """\n'
        "    return value\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["docstring-args-restate-signature", "no-docstring-type-restatement"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ086", "SARJ086"]
    assert [finding.line for finding in diagnostics] == [2, 10]


def test_nominal_id_boundary_suppresses_generic_swap_prone_signature(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def transfer(\n    source_account_id: str,\n    destination_account_id: str,\n) -> None: ...\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["require-keyword-only-swap-prone-params", "prefer-nominal-id-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ093"]


def test_any_mapping_owns_fixed_record_overlap(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "from typing import Any\ndef payload() -> dict[str, Any]:\n    return {'id': 1}\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["named-record-at-boundaries", "no-any-mapping-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ447"]
    assert diagnostics[0].severity is Severity.ERROR
    assert "TypedDict" in diagnostics[0].message


def test_fastapi_contract_owns_visible_any_mapping_overlap(tmp_path: Path) -> None:
    source = tmp_path / "api.py"
    source.write_text(
        "from typing import Any\n"
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        "@router.get('/health')\n"
        "async def health() -> dict[str, Any]:\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )

    diagnostics = analyze(
        ["fastapi-explicit-openapi-contract", "named-record-at-boundaries", "no-any-mapping-types"], [source]
    )

    assert [finding.code for finding in diagnostics] == ["SARJ094", "SARJ094"]


def test_fastapi_precedence_preserves_any_mapping_when_route_contract_is_complete(tmp_path: Path) -> None:
    source = tmp_path / "api.py"
    source.write_text(
        "from typing import Any\n"
        "from fastapi import APIRouter\n"
        "from pydantic import BaseModel\n\n"
        "router = APIRouter()\n\n"
        "class HealthResponse(BaseModel):\n"
        "    status: str\n\n"
        "@router.get('/health', status_code=200, response_model=HealthResponse)\n"
        "async def health() -> dict[str, Any]:\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["fastapi-explicit-openapi-contract", "no-any-mapping-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ447"]


def test_fastapi_metadata_does_not_hide_independent_any_mapping(tmp_path: Path) -> None:
    source = tmp_path / "api.py"
    source.write_text(
        "from typing import Any\n"
        "from fastapi import APIRouter\n"
        "from pydantic import BaseModel\n\n"
        "router = APIRouter()\n\n"
        "class HealthResponse(BaseModel):\n"
        "    status: str\n\n"
        "@router.get('/health', response_model=HealthResponse)\n"
        "async def health() -> dict[str, Any]:\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["fastapi-explicit-openapi-contract", "no-any-mapping-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ094", "SARJ447"]


def test_fastapi_precedence_never_crosses_function_owners(tmp_path: Path) -> None:
    source = tmp_path / "api.py"
    source.write_text(
        "from typing import Any\n"
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        "@router.get('/health')\n"
        "async def health() -> dict[str, Any]:\n"
        "    return {'status': 'ok'}\n\n"
        "def serialize() -> dict[str, Any]:\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["fastapi-explicit-openapi-contract", "no-any-mapping-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ094", "SARJ094", "SARJ447"]


def test_comment_only_unit_warning_remains_when_selected_alone(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("# Timeout in seconds.\nTIMEOUT = 5\n", encoding="utf-8")

    diagnostics = analyze(["prefer-self-documenting-constant"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ097"]


def test_precedence_never_crosses_source_locations() -> None:
    diagnostics = [_diagnostic("SARJ050", line=2), _diagnostic("SARJ088", line=3)]

    assert deduplicate_diagnostics(diagnostics) == diagnostics


def test_specific_warning_never_hides_a_generic_error() -> None:
    generic = Diagnostic(Path("service.py"), 3, 5, "SARJ050", "generic", Severity.ERROR)
    specific = Diagnostic(Path("service.py"), 3, 5, "SARJ084", "specific", Severity.WARNING)

    assert deduplicate_diagnostics([generic, specific]) == [generic, specific]


def test_suppressing_specific_finding_preserves_unsuppressed_generic_twin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "test_service.py"
    source.write_text(
        "def test_returns_none_when_missing():\n"
        '    """Test returns None when missing."""  # sarj-noqa: SARJ088\n'
        "    assert lookup() is None\n",
        encoding="utf-8",
    )

    status = main(
        [
            "check",
            "--rule",
            "redundant-docstring",
            "--rule",
            "restated-test-docstring",
            str(source),
        ]
    )

    assert status == 0
    output = capsys.readouterr().out
    assert "SARJ050 warning:" in output
    assert "SARJ088" not in output
