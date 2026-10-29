from __future__ import annotations

import ast
import cProfile
from itertools import permutations
from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.__main__ import analyze, deduplicate_diagnostics, main
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Diagnostic, Severity


if TYPE_CHECKING:
    import pytest


def _diagnostic(code: str, *, line: int = 3) -> Diagnostic:
    return Diagnostic(Path("service.py"), line, 5, code, code)


def test_specific_test_docstring_finding_suppresses_generic_restatements() -> None:
    diagnostics = [_diagnostic("SARJ050"), _diagnostic("SARJ085"), _diagnostic("SARJ088")]

    assert [finding.code for finding in deduplicate_diagnostics(diagnostics)] == ["SARJ088"]


def test_repeated_composition_owns_wide_setup_at_same_call() -> None:
    diagnostics = [_diagnostic("SARJ045"), _diagnostic("SARJ457"), _diagnostic("SARJ045", line=4)]

    assert [(finding.code, finding.line) for finding in deduplicate_diagnostics(diagnostics)] == [
        ("SARJ457", 3),
        ("SARJ045", 4),
    ]


def test_proven_service_contract_finding_owns_advisory_at_same_class() -> None:
    diagnostics = [
        Diagnostic(Path("service.py"), 3, 5, "SARJ071", "advisory", Severity.WARNING),
        Diagnostic(Path("service.py"), 3, 5, "SARJ465", "contract", Severity.WARNING),
        Diagnostic(Path("service.py"), 7, 5, "SARJ071", "other", Severity.WARNING),
    ]
    assert [(finding.code, finding.line) for finding in deduplicate_diagnostics(diagnostics)] == [
        ("SARJ465", 3),
        ("SARJ071", 7),
    ]


def test_repeated_body_owns_composition_only_inside_its_test() -> None:
    source = "def test_one():\n    service = build()\n    service.run()\n\ndef test_two():\n    service = build()\n"
    diagnostics = [
        _diagnostic("SARJ066", line=1),
        _diagnostic("SARJ457", line=2),
        _diagnostic("SARJ457", line=6),
    ]

    assert [(finding.code, finding.line) for finding in deduplicate_diagnostics(diagnostics, source=source)] == [
        ("SARJ066", 1),
        ("SARJ457", 6),
    ]


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

    assert [finding.code for finding in diagnostics] == ["SARJ092"]
    assert diagnostics[0].severity is Severity.ERROR
    assert diagnostics[0].line == 5


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

    assert [finding.code for finding in diagnostics] == ["SARJ092"]
    assert diagnostics[0].severity is Severity.ERROR
    assert diagnostics[0].line == 5


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

    assert [finding.code for finding in diagnostics] == ["SARJ086", "SARJ092"]
    assert [finding.line for finding in diagnostics] == [10, 5]


def test_nominal_id_boundary_suppresses_generic_swap_prone_signature(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def transfer(\n    source_account_id: str,\n    destination_account_id: str,\n) -> None: ...\n",
        encoding="utf-8",
    )

    diagnostics = analyze(["require-keyword-only-swap-prone-params", "prefer-nominal-id-types"], [source])

    assert [finding.code for finding in diagnostics] == ["SARJ093"]


def test_nominal_and_closed_string_findings_are_order_independent(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def move(file_id: str, folder_id: str) -> None: ...\n\n"
        "def render(kind: str) -> str:\n"
        "    if kind not in {'text', 'image'}:\n"
        "        raise ValueError('unsupported kind')\n"
        "    return kind\n",
        encoding="utf-8",
    )
    selectors = ("prefer-nominal-id-types", "prefer-str-enum", "require-keyword-only-swap-prone-params")

    for order in permutations(selectors):
        diagnostics = analyze(list(order), [source])
        assert sorted((finding.code, finding.line, finding.severity) for finding in diagnostics) == [
            ("SARJ006", 4, Severity.ERROR),
            ("SARJ093", 1, Severity.ERROR),
        ]


def test_nominal_and_closed_domain_remediation_converges(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "from enum import StrEnum\nfrom typing import NewType\n\n"
        "FileId = NewType('FileId', str)\nFolderId = NewType('FolderId', str)\n\n"
        "class Kind(StrEnum):\n    TEXT = 'text'\n    IMAGE = 'image'\n\n"
        "def move(file_id: FileId, folder_id: FolderId) -> None: ...\n\n"
        "def render(kind: Kind, *, service_version: str = 'dev') -> str:\n"
        "    if kind not in {Kind.TEXT, Kind.IMAGE}:\n"
        "        raise ValueError('unsupported kind')\n"
        "    return service_version\n",
        encoding="utf-8",
    )
    selectors = ["prefer-nominal-id-types", "prefer-str-enum", "require-keyword-only-swap-prone-params"]

    assert analyze(selectors, [source]) == []
    assert analyze(selectors, [source]) == []


def test_nominal_and_enum_cli_suppressions_remain_independent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def move(file_id: str, folder_id: str) -> None: ...  # sarj-noqa: SARJ093\n\n"
        "def render(kind: str) -> str:\n"
        "    if kind not in {'text', 'image'}:\n"
        "        raise ValueError('unsupported kind')\n"
        "    return kind\n",
        encoding="utf-8",
    )
    arguments = ["check", "--rule", "prefer-nominal-id-types", "--rule", "prefer-str-enum", str(source)]

    assert main(arguments) == 1
    output = capsys.readouterr().out
    assert "SARJ006" in output
    assert "SARJ093" not in output

    source.write_text(source.read_text().replace("{'text', 'image'}:", "{'text', 'image'}:  # sarj-noqa: SARJ006"))
    assert main(arguments) == 0
    assert not capsys.readouterr().out


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

    assert status == 1
    output = capsys.readouterr().out
    assert "SARJ050 " in output
    assert "warning:" not in output
    assert "SARJ088" not in output


def test_owner_precedence_shares_one_parse_and_reuses_a_file_context() -> None:
    source = 'def test_one(\n    value,\n):\n    """\n    Args: value\n    """\n    return build(value)\n'
    diagnostics = [
        Diagnostic(Path("service.py"), line, 1, code, code)
        for code, line in [
            ("SARJ066", 1),
            ("SARJ457", 7),
            ("SARJ092", 5),
            ("SARJ086", 5),
            ("SARJ093", 1),
            ("SARJ034", 2),
        ]
    ]
    expected = [("SARJ066", 1), ("SARJ092", 5), ("SARJ093", 1)]
    profile = cProfile.Profile()
    findings = profile.runcall(deduplicate_diagnostics, diagnostics, source=source)
    assert [(finding.code, finding.line) for finding in findings] == expected
    assert sum(entry.callcount for entry in profile.getstats() if entry.code is ast.parse.__code__) == 1
    context = PythonFileContext(Path("service.py"), source)
    assert context.tree is not None
    profile = cProfile.Profile()
    findings = profile.runcall(deduplicate_diagnostics, diagnostics, source=source, context=context)
    assert not any(entry.code is ast.parse.__code__ for entry in profile.getstats())
    assert [(finding.code, finding.line) for finding in findings] == expected


def test_owner_precedence_preserves_findings_when_source_cannot_parse() -> None:
    diagnostics = [_diagnostic(code) for code in ("SARJ066", "SARJ457", "SARJ092", "SARJ086", "SARJ093", "SARJ034")]
    source = "def broken(:"
    expected = deduplicate_diagnostics(diagnostics)
    assert deduplicate_diagnostics(diagnostics, source=source) == expected
    context = PythonFileContext(Path("service.py"), source)
    assert deduplicate_diagnostics(diagnostics, source=source, context=context) == expected


def test_native_http_client_precedence_preserves_standalone_fixture_advice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "test_client.py"
    clients = "from httpx import AsyncClient, ASGITransport, Client\n" + "\n".join(
        f"async def test_case_{number}(app):\n"
        "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:\n"
        "        assert await client.get('/')\n"
        for number in range(3)
    )
    source.write_text(
        clients + "\ndef test_sync_client():\n    client = Client()\n    assert client\n", encoding="utf-8"
    )
    assert main(["check", "--rule", "prefer-pytest-dependency-fixtures", str(source)]) == 0
    standalone = capsys.readouterr().out
    assert standalone.count("SARJ526") == 4
    assert (
        main(
            ["check", "--rule", "prefer-pytest-dependency-fixtures", "--rule", "repeated-test-composition", str(source)]
        )
        == 1
    )
    combined = capsys.readouterr().out
    assert combined.count("SARJ457") == 3
    assert combined.count("SARJ526") == 1


def test_native_phase_comment_precedence_preserves_standalone_comment_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "test_ready.py"
    source.write_text(
        "def test_ready():\n    # Arrange\n    value = 1\n    # A stale value is rejected.\n    assert value\n",
        encoding="utf-8",
    )
    assert main(["check", "--rule", "no-test-comments", str(source)]) == 0
    standalone = capsys.readouterr().out
    assert standalone.count("SARJ551") == 2
    assert main(["check", "--rule", "no-test-comments", "--rule", "no-bare-test-phase-comments", str(source)]) == 1
    combined = capsys.readouterr().out
    assert combined.count("SARJ089") == 1
    assert combined.count("SARJ551") == 1
    source.write_text(
        "def test_ready():\n    # Arrange\n    value = 1\n    # A stale value is rejected.  # sarj-noqa: SARJ551 -- external protocol rationale\n    assert value\n",
        encoding="utf-8",
    )
    assert main(["check", "--rule", "no-test-comments", "--rule", "no-bare-test-phase-comments", str(source)]) == 1
    suppressed = capsys.readouterr().out
    assert suppressed.count("SARJ089") == 1
    assert "SARJ551" not in suppressed
