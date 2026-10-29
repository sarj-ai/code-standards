from __future__ import annotations

from dataclasses import replace
from functools import partial
from itertools import permutations
from pathlib import Path

import pytest

from sarj_python_lint.__main__ import check_source, deduplicate_diagnostics
from sarj_python_lint.rule_base import (
    ColumnEncoding,
    Diagnostic,
    DiagnosticSubject,
    Severity,
)
from sarj_python_lint.rules.fastapi_explicit_openapi_contract import FastapiExplicitOpenapiContract
from sarj_python_lint.rules.no_any_mapping_types import NoAnyMappingTypes


_PATH = Path("api.py")
_PRELUDE = (
    "from typing import Any\n"
    "from fastapi import APIRouter\n"
    "from pydantic import BaseModel\n\n"
    "router = APIRouter()\n\n"
    "class Payload(BaseModel):\n    id: int\n\n"
)
_ERASED_RETURN = (
    f"{_PRELUDE}@router.get('/items', status_code=200)\nasync def items() -> dict[str, Any]:\n    return {{'id': 1}}\n"
)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(
            "@router.get('/items', status_code=200)\nasync def items() -> dict[str, Any]:\n    return {'id': 1}\n",
            id="declared-return",
        ),
        pytest.param(
            "@router.get('/items', status_code=200)\nasync def items():\n    return {'id': 1}\n",
            id="inferred-return",
        ),
        pytest.param(
            "@router.get('/items', status_code=200, response_model=Payload, response_model_include={'id'})\n"
            "async def items() -> Payload:\n    return Payload(id=1)\n",
            id="response-projection",
        ),
    ],
)
def test_all_return_producers_retain_precedence_when_their_messages_are_rewritten(handler: str) -> None:
    source = _PRELUDE + handler
    [specific] = FastapiExplicitOpenapiContract().check(_PATH, source)
    assert specific.subject is DiagnosticSubject.RETURN
    generic = Diagnostic(_PATH, specific.line, specific.col, "SARJ008", "Generic return diagnostic")
    rewritten = replace(specific, message="The response contract needs an explicit named type.")

    for diagnostics in permutations((specific, generic)):
        assert deduplicate_diagnostics(list(diagnostics), source=source) == [specific]
    for diagnostics in permutations((rewritten, generic)):
        assert deduplicate_diagnostics(list(diagnostics), source=source) == [rewritten]


def test_real_return_diagnostics_keep_owner_path_severity_and_order_boundaries_after_rewording() -> None:
    source = _ERASED_RETURN + "\ndef serialize() -> dict[str, Any]:\n    return {'id': 1}\n"
    [specific] = FastapiExplicitOpenapiContract().check(_PATH, source)
    generics = NoAnyMappingTypes().check(_PATH, source)
    assert len(generics) == 2
    assert specific.severity is Severity.WARNING
    assert all(generic.severity is Severity.ERROR for generic in generics)
    rewritten = replace(specific, message="Different display wording, same return contract.")
    other_path = replace(generics[0], path=Path("other.py"))
    outside = generics[1]

    for diagnostics in permutations((rewritten, *generics, other_path)):
        expected = [item for item in diagnostics if item is not generics[0]]
        actual = deduplicate_diagnostics(list(diagnostics), source=source)
        assert actual == expected
        assert rewritten in actual
        assert outside in actual
        assert other_path in actual


def test_nonreturn_diagnostic_cannot_claim_precedence_through_return_looking_wording() -> None:
    source = (
        f"{_PRELUDE}@router.get('/items', status_code=200, response_model=Payload)\n"
        "async def items(limit: int) -> dict[str, Any]:\n    return {'id': limit}\n"
    )
    [parameter] = FastapiExplicitOpenapiContract().check(_PATH, source)
    [generic] = NoAnyMappingTypes().check(_PATH, source)
    assert parameter.subject is None
    rewritten = replace(parameter, message="[return] wording does not declare diagnostic identity.")

    for diagnostics in permutations((rewritten, generic)):
        assert deduplicate_diagnostics(list(diagnostics), source=source) == list(diagnostics)


def test_projection_subject_does_not_change_existing_decorator_and_signature_owners() -> None:
    source = (
        f"{_PRELUDE}@router.get('/items', status_code=200, response_model=Payload, response_model_include={{'id'}})\n"
        "async def items() -> dict[str, Any]:\n    return {'id': 1}\n"
    )
    [projection] = FastapiExplicitOpenapiContract().check(_PATH, source)
    [generic] = NoAnyMappingTypes().check(_PATH, source)
    assert projection.subject is DiagnosticSubject.RETURN
    rewritten = replace(projection, message="A dedicated output model describes this response projection.")

    assert deduplicate_diagnostics([rewritten, generic], source=source) == [rewritten, generic]


def test_suppressed_return_subject_does_not_hide_the_unsuppressed_generic() -> None:
    source = _ERASED_RETURN.replace(
        "async def items() -> dict[str, Any]:",
        "async def items() -> dict[str, Any]:  # sarj-noqa: SARJ094 -- retain the local return contract exception",
    )

    findings = check_source([FastapiExplicitOpenapiContract(), NoAnyMappingTypes()], _PATH, source)

    assert [finding.code for finding in findings] == ["SARJ447"]


def test_legacy_untagged_return_looking_diagnostic_conservatively_keeps_the_generic() -> None:
    [specific] = FastapiExplicitOpenapiContract().check(_PATH, _ERASED_RETURN)
    [generic] = NoAnyMappingTypes().check(_PATH, _ERASED_RETURN)
    legacy = replace(specific, subject=None)
    assert legacy.message.startswith("[return]")

    assert deduplicate_diagnostics([legacy, generic], source=_ERASED_RETURN) == [legacy, generic]


def _legacy_consumer_diagnostic(path: Path) -> Diagnostic:
    return Diagnostic(path, 3, 5, "SARJ094", "[return] legacy wording", Severity.WARNING, ColumnEncoding.CODEPOINTS, ())


def test_consumer_keeps_all_eight_positional_fields_match_args_and_cli_format() -> None:
    diagnostic = _legacy_consumer_diagnostic(_PATH)

    assert diagnostic.subject is None
    assert diagnostic.column_encoding is ColumnEncoding.CODEPOINTS
    assert diagnostic.fixes == ()
    assert diagnostic.format() == "api.py:3:5: SARJ094 warning: [return] legacy wording"
    assert Diagnostic.__match_args__ == (
        "path",
        "line",
        "col",
        "code",
        "message",
        "severity",
        "column_encoding",
        "fixes",
    )
    assert replace(diagnostic, subject=DiagnosticSubject.RETURN).format() == diagnostic.format()
    construct = partial(Diagnostic, _PATH, 3, 5, "SARJ094", "legacy", Severity.WARNING, ColumnEncoding.CODEPOINTS, ())
    with pytest.raises(TypeError):
        construct(DiagnosticSubject.RETURN)  # pyright: ignore[reportCallIssue] -- Prove the ninth positional argument is rejected by the real keyword-only constructor.


@pytest.mark.parametrize("subject", ["return", "unknown", 1, True])
def test_untyped_subject_cannot_silently_acquire_semantic_precedence(subject: str | int) -> None:
    diagnostic = _legacy_consumer_diagnostic(_PATH)

    with pytest.raises(TypeError, match="DiagnosticSubject or None"):
        replace(diagnostic, subject=subject)
