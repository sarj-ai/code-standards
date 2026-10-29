from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_custom_control_flow_exception import NoCustomControlFlowException


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


P = Path("app/content.py")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return NoCustomControlFlowException().check(path, source)


def test_documented_examples() -> None:
    verify_native_rule(NoCustomControlFlowException, analyze)


@pytest.mark.parametrize("body", ["pass", "...", "'Invalid input'", "'Invalid input'\n    pass"])
@pytest.mark.parametrize("base", ["Exception", "ValueError"])
def test_name_only_raised_markers(body: str, base: str) -> None:
    source = f"class DomainError({base}):\n    {body}\ndef read():\n    raise DomainError('unsupported')\n"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].line == 1
    assert "typed tagged result" in findings[0].message


@pytest.mark.parametrize(
    "raise_expression", ["DomainError", "DomainError()", "DomainError('unsupported')", "DomainError() from cause"]
)
def test_raise_forms_and_explicit_handling(raise_expression: str) -> None:
    source = f"class DomainError(Exception): pass\ndef read():\n    try:\n        raise {raise_expression}\n    except (DomainError, TypeError):\n        return None\n"
    assert len(_check(source)) == 1


def test_empty_local_subclass_retains_local_base_identity() -> None:
    source = "class DomainError(Exception): pass\nclass Missing(DomainError): pass\ndef read():\n    raise Missing\n"
    findings = _check(source)
    assert len(findings) == 1
    assert "Missing" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "class DomainError(Exception): pass\n",
        "class DomainError(RuntimeError): pass\ndef read():\n    raise DomainError\n",
        "from external import DomainError\ndef read():\n    raise DomainError\n",
        "from fastapi import HTTPException\nclass DomainError(HTTPException): pass\ndef read():\n    raise DomainError\n",
        "class DomainError(BaseException): pass\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception):\n    code: str\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception):\n    def __init__(self, code): self.code = code\ndef read():\n    raise DomainError('missing')\n",
        "@decorate\nclass DomainError(Exception): pass\ndef read():\n    raise DomainError\n",
        "class DomainError[T](Exception): pass\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception, Other): pass\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception): pass\nregister_handler(DomainError)\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception): pass\nalias = DomainError\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception): pass\nDomainError.flag = True\ndef read():\n    raise DomainError\n",
        "class DomainError(Exception): pass\ndef read(DomainError):\n    raise DomainError\n",
        "class DomainError(Exception): pass\nDomainError = other\ndef read():\n    raise DomainError\n",
        "class ValueError: pass\nclass DomainError(ValueError): pass\ndef read():\n    raise DomainError\n",
        "ValueError = Other\nValueError = Another\nclass DomainError(ValueError): pass\ndef read():\n    raise DomainError\n",
    ],
)
def test_unknown_exception_contracts_and_escaping_markers(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "decorator",
    ["field_validator('value')", "model_validator(mode='before')", "validator('value')", "root_validator()"],
)
def test_pydantic_rejection_protocol(decorator: str) -> None:
    source = f"from pydantic import field_validator, model_validator, validator, root_validator\nclass DomainError(ValueError): pass\nclass Model:\n    @{decorator}\n    def validate(cls, value):\n        raise DomainError\n"
    assert _check(source) == []


def test_ordinary_raise_still_warns_beside_validator_raise() -> None:
    source = "from pydantic import field_validator\nclass DomainError(ValueError): pass\nclass Model:\n    @field_validator('value')\n    def validate(cls, value):\n        raise DomainError\ndef read():\n    raise DomainError\n"
    assert len(_check(source)) == 1


def test_exception_base_does_not_borrow_value_error_validation_protocol() -> None:
    source = "from pydantic import field_validator\nclass DomainError(Exception): pass\nclass Model:\n    @field_validator('value')\n    def validate(cls, value):\n        raise DomainError\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "path",
    [Path("tests/content.py"), Path("vendor/content.py"), Path("generated/content.py")],
    ids=["test", "vendor", "generated"],
)
def test_external_ownership(path: Path) -> None:
    assert _check("class DomainError(Exception): pass\ndef read():\n    raise DomainError\n", path) == []


def test_exact_suppression_and_malformed_source() -> None:
    source = "class DomainError(Exception):  # sarj-noqa: SARJ542 -- framework requires this public marker\n    pass\ndef read():\n    raise DomainError\n"
    assert _check(source) == []
    assert check_source([NoCustomControlFlowException()], P, source) == []
    assert _check("class DomainError(Exception):\n    (") == []


@pytest.mark.parametrize(
    "base_use",
    [
        "register_handler(Base)",
        "handler_types = {Base: handler}",
        "alias = Base",
        "Base.code = 400",
        "del Base.code",
        "def replace():\n    global Base\n    Base = Other\nreplace()",
    ],
)
@pytest.mark.parametrize("depth", [1, 3])
def test_inherited_escaped_or_mutated_contract_abstains(base_use: str, depth: int) -> None:
    declarations = ["class Base(Exception): pass", base_use]
    parent = "Base"
    for index in range(depth):
        name = f"Child{index}"
        declarations.append(f"class {name}({parent}): pass")
        parent = name
    source = "\n".join([*declarations, f"raise {parent}", ""])
    assert _check(source) == []


@pytest.mark.parametrize("depth", [1, 3])
def test_stable_local_inheritance_still_warns(depth: int) -> None:
    declarations = ["class Base(Exception): pass"]
    parent = "Base"
    for index in range(depth):
        name = f"Child{index}"
        declarations.append(f"class {name}({parent}): pass")
        parent = name
    source = "\n".join([*declarations, f"raise {parent}", ""])
    findings = _check(source)
    assert len(findings) == 1
    assert f"`{parent}`" in findings[0].message


def test_an_unrelated_escaped_marker_does_not_hide_a_stable_marker() -> None:
    source = (
        "class Registered(Exception): pass\n"
        "register_handler(Registered)\n"
        "class DomainError(Exception): pass\n"
        "raise DomainError\n"
    )
    findings = _check(source)
    assert len(findings) == 1
    assert "`DomainError`" in findings[0].message


@pytest.mark.parametrize("ordinary_first", [False, True])
def test_raise_index_preserves_validator_and_ordinary_raise_order(ordinary_first: bool) -> None:
    validator = "class Model:\n    @field_validator('value')\n    def validate(cls, value): raise DomainError\n"
    ordinary = "def read(): raise DomainError\n"
    source = "from pydantic import field_validator\nclass DomainError(ValueError): pass\n" + (
        ordinary + validator if ordinary_first else validator + ordinary
    )
    assert len(_check(source)) == 1


def test_multiple_markers_and_repeated_raises_report_each_definition_once() -> None:
    source = (
        "class First(Exception): pass\n"
        "class Second(Exception): pass\n"
        "def read(value):\n"
        "    if value == 1: raise First\n"
        "    if value == 2: raise First()\n"
        "    raise Second from None\n"
    )
    findings = _check(source)
    assert [finding.line for finding in findings] == [1, 2]


def test_global_rebinding_of_a_direct_marker_abstains() -> None:
    source = (
        "class DomainError(Exception): pass\n"
        "def replace():\n"
        "    global DomainError\n"
        "    DomainError = Other\n"
        "replace()\n"
        "raise DomainError\n"
    )
    assert _check(source) == []
