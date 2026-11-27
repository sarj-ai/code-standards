from textwrap import indent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_failure_conflated_with_absence import NoFailureConflatedWithAbsence


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


_RULE = "no-failure-conflated-with-absence"
_SOURCE = """\
from pydantic import ValidationError

async def lookup(store, key: str) -> str | None:
    try:
        row = await store.get(key)
    except ValidationError:
        logger.warning("Invalid stored record")
        return None
    return None
"""
_FALLTHROUGH = _SOURCE.removesuffix("    return None\n")
_HANDLER_ONLY = _FALLTHROUGH + "    return row\n"


def _findings(tmp_path: Path, source: str, relative: str = "lookup.py") -> list[Diagnostic]:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return analyze([_RULE], [path])


def test_documented_examples() -> None:
    verify_native_rule(NoFailureConflatedWithAbsence, analyze)


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        pytest.param(
            _FALLTHROUGH + "    if row is None:\n        return None\n    return row.value\n",
            [8],
            id="invalid-record-or-absent",
        ),
        pytest.param(
            """\
import json
def decode(value: object) -> dict[str, str] | None:
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except ValueError, json.JSONDecodeError:
        return None
""",
            [8],
            id="malformed-or-rejected-payload",
        ),
        pytest.param(
            """\
from pydantic import ValidationError
def dispatch(kind: str, payload: bytes) -> Event | None:
    match kind:
        case "event":
            try:
                return Event.model_validate_json(payload)
            except ValidationError:
                return None
        case _:
            return None
""",
            [8],
            id="invalid-or-unsubscribed-event",
        ),
        pytest.param(
            """\
from pydantic import ValidationError
def validated_card(answer: str) -> Card | None:
    if not answer:
        return None
    try:
        return Card.model_validate_json(answer)
    except (ValidationError, ValueError):
        return None
""",
            [8],
            id="invalid-or-empty-answer",
        ),
        pytest.param(
            """\
from google.auth.exceptions import GoogleAuthError
def verifier(client):
    def verified_email(token: str) -> str | None:
        try:
            claims = client.verify(token)
        except GoogleAuthError:
            return None
        if not claims.email_verified:
            return None
        return claims.email
    return verified_email
""",
            [7],
            id="verification-failure-or-unverified-email",
        ),
        pytest.param(_FALLTHROUGH, [8], id="implicit-normal-absence"),
        pytest.param(
            _FALLTHROUGH.replace("from pydantic import ValidationError", "from typing import Optional as Maybe")
            .replace("str | None", '"Result"')
            .replace("async def", "type Result = Maybe[str]\n\nasync def")
            .replace("except ValidationError:", "except (KeyError, OSError):")
            .replace("        return None", "        return")
            + "    else:\n        return\n",
            [10],
            id="quoted-alias-and-bare-returns",
        ),
    ],
)
def test_reports_handler_returns(tmp_path: Path, source: str, lines: list[int]) -> None:
    findings = _findings(tmp_path, source)
    assert [(item.line, item.code, item.severity, item.fixes) for item in findings] == [
        (line, "SARJ601", Severity.WARNING, ()) for line in lines
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def is_uuid(value: str) -> bool:\n    try:\n        return check_uuid(value)\n"
            "    except ValueError:\n        return False\n",
            id="boolean-predicate",
        ),
        pytest.param(
            _HANDLER_ONLY.replace("ValidationError:", "(OSError, IndexError, ValueError):"),
            id="memory-probe-handler-only",
        ),
        pytest.param(
            "from app.subject import NoSubjectFoundError\n"
            "def organization_id(request) -> int | None:\n    try:\n        return subject(request).organization_id\n"
            "    except NoSubjectFoundError:\n        return None\n",
            id="subject-lookup-handler-only",
        ),
        pytest.param(
            _HANDLER_ONLY.replace(
                "    return row\n", "    try:\n        return row.value\n    except ValueError:\n        return None\n"
            ),
            id="none-only-in-different-handlers",
        ),
        pytest.param(_SOURCE.replace("ValidationError:", "KeyError:"), id="expected-lookup"),
        pytest.param(
            "from builtins import FileNotFoundError as Missing\n"
            + _SOURCE.replace("ValidationError:", "(Missing, LookupError):"),
            id="qualified-lookup-only",
        ),
        pytest.param(_SOURCE.replace("ValidationError:", "(ValueError, Exception):"), id="ruff-broad"),
        pytest.param(
            "from asyncio.exceptions import CancelledError as Cancelled\n"
            + _SOURCE.replace("ValidationError:", "Cancelled:"),
            id="asyncio-cancellation",
        ),
        pytest.param(_SOURCE.replace("str | None", "list[str | None]"), id="nested-nullable"),
        pytest.param(
            "from typing import Optional\n"
            "def scope():\n    from contracts import Optional\n"
            "    def lookup() -> Optional[int]:\n"
            "        try:\n            value = read()\n"
            "        except ValueError:\n            return None\n"
            "        return None\n",
            id="shadowed-optional",
        ),
        pytest.param(_SOURCE.replace("str | None", "None"), id="none-only-annotation"),
        pytest.param(
            _SOURCE.replace("async def", "type Maybe = Maybe | None\n\nasync def").replace("str | None", "Maybe"),
            id="recursive-alias",
        ),
        pytest.param(_SOURCE.replace("    try:", "    yield key\n    try:"), id="generator"),
        pytest.param(_SOURCE.replace("lookup(", "__call__("), id="dunder"),
        pytest.param(
            "from typing_extensions import override as method_override\n"
            + _SOURCE.replace("async def lookup", "@method_override\nasync def lookup"),
            id="override",
        ),
        pytest.param(_SOURCE.replace("except ValidationError:", "except failures[0]:"), id="dynamic-type"),
        pytest.param(_SOURCE.replace("key: str", "key: str, ValidationError"), id="shadowed-exception"),
        pytest.param(_SOURCE.replace("logger.warning", "metrics.warning"), id="effectful-handler"),
        pytest.param(_HANDLER_ONLY + "    return None\n", id="unreachable-normal-return"),
        pytest.param(
            _FALLTHROUGH + "    for key in ['required']:\n        return key\n",
            id="nonempty-loop-returns",
        ),
        pytest.param(
            _FALLTHROUGH + "    for item in []:\n        return None\n    return row.value\n",
            id="unreachable-empty-loop-body",
        ),
        pytest.param(
            _FALLTHROUGH + "    match key:\n        case 'known':\n            return 'value'\n    return None\n",
            id="no-implicit-match-fallthrough",
        ),
        pytest.param(
            _FALLTHROUGH + "    finally:\n        return 'value'\n",
            id="overridden-return",
        ),
        pytest.param(_SOURCE.replace("except ValidationError:", "except* ValidationError:"), id="except-star-return"),
    ],
)
def test_leaves_other_contracts_alone(tmp_path: Path, source: str) -> None:
    assert _findings(tmp_path, source) == []


def test_public_inherited_method_is_excluded(tmp_path: Path) -> None:
    imports, definition = _SOURCE.split("async def", 1)
    method = indent("async def" + definition, "    ")
    assert _findings(tmp_path, imports + "class Lookup(Contract):\n" + method) == []


@pytest.mark.parametrize(
    ("declaration", "lines"),
    [
        pytest.param("class BadRecord(ValueError): ...\n", [8], id="failure"),
        pytest.param("class BadRecord(KeyError): ...\n", [], id="lookup-signal"),
        pytest.param("class BadRecord(ValueError): ...\nBadRecord = LookupError\n", [], id="rebound"),
    ],
)
def test_resolves_first_party_exception(tmp_path: Path, declaration: str, lines: list[int]) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n')
    (tmp_path / "app").mkdir()
    (tmp_path / "app/__init__.py").touch()
    (tmp_path / "app/failures.py").write_text(declaration)
    source = _SOURCE.replace(
        "from pydantic import ValidationError", "from .failures import BadRecord as ValidationError"
    )
    assert [finding.line for finding in _findings(tmp_path, source, "app/lookup.py")] == lines


def test_malformed_input_keeps_native_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="selected Python source could not be parsed"):
        _findings(tmp_path, _SOURCE.replace("except ValidationError:", "except ValidationError"))


def test_excludes_generated_tests_and_exact_suppression(tmp_path: Path) -> None:
    assert _findings(tmp_path, _SOURCE, "tests/test_lookup.py") == []
    assert _findings(tmp_path, "# @generated\n" + _SOURCE) == []
    suppressed = _SOURCE.replace("        return None", "        return None  # sarj-noqa: SARJ601 -- API boundary")
    assert _findings(tmp_path, suppressed) == []
    assert [item.line for item in _findings(tmp_path, suppressed.replace("SARJ601", "SARJ597"))] == [8]
