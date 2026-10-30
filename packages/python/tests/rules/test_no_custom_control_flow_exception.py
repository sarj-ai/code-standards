from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import AutofixPolicy, Severity
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


@pytest.mark.parametrize("imported", ["Exception", "ValueError", "Exception as ErrorBase", "ValueError as ErrorBase"])
def test_direct_builtin_exception_import_retains_review_identity(imported: str) -> None:
    base = imported.rsplit(" as ", maxsplit=1)[-1]
    source = f"from builtins import {imported}\nclass DomainError({base}): pass\ndef read(): raise DomainError\n"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].fixes == ()
    documentation = NoCustomControlFlowException.documentation
    assert documentation is not None
    assert documentation.autofix is AutofixPolicy.NONE


@pytest.mark.parametrize(
    ("prefix", "base"),
    [
        ("import builtins as b", "b.Exception"),
        ("import builtins as b\nb.Exception = Other", "Exception"),
        ("from builtins import setattr as change", "Exception"),
        ("from builtins import ValueError as ErrorBase\nErrorBase = Other", "ErrorBase"),
        ("from builtins import ValueError as ErrorBase\nregister(ErrorBase)", "ErrorBase"),
        ("from builtins import ValueError as ErrorBase\nErrorBase.flag = Other", "ErrorBase"),
    ],
)
def test_imported_builtin_namespace_and_identity_hazards_still_abstain(prefix: str, base: str) -> None:
    assert _check(f"{prefix}\nclass DomainError({base}): pass\nraise DomainError\n") == []


@pytest.mark.parametrize(
    "module",
    ["pydantic.class_validators", "pydantic.v1.class_validators", "pydantic.deprecated.class_validators"],
)
@pytest.mark.parametrize(("symbol", "arguments"), [("validator", "'value'"), ("root_validator", "pre=True")])
@pytest.mark.parametrize("ordinary_raise", [False, True])
def test_import_proven_legacy_validator_export_paths(
    module: str, symbol: str, arguments: str, *, ordinary_raise: bool
) -> None:
    source = (
        "from builtins import ValueError as ErrorBase\n"
        f"from {module} import {symbol} as check\n"
        "class Parent(ErrorBase): pass\nclass DomainError(Parent): pass\n"
        f"class Model:\n    @check({arguments})\n    def validate(cls, value): raise DomainError\n"
    )
    if ordinary_raise:
        source += "def read(): raise DomainError\n"
    assert len(_check(source)) == int(ordinary_raise)


_FUNCTIONAL_SOURCE = (
    "from typing import Annotated\n"
    "from pydantic import BaseModel, AfterValidator\n"
    "class DomainError(ValueError): pass\n"
    "def reject(value): raise DomainError('rejected')\n"
    "class Model(BaseModel):\n"
    "    value: Annotated[int, AfterValidator(reject)]\n"
)


@pytest.mark.parametrize("module", ["pydantic", "pydantic.functional_validators"])
@pytest.mark.parametrize("constructor", ["AfterValidator", "BeforeValidator", "PlainValidator", "WrapValidator"])
@pytest.mark.parametrize("keyword_argument", [False, True])
def test_exclusive_annotated_validator_callback_preserves_rejection(
    module: str, constructor: str, *, keyword_argument: bool
) -> None:
    argument = "func=reject" if keyword_argument else "reject"
    source = _FUNCTIONAL_SOURCE.replace(
        "from pydantic import BaseModel, AfterValidator",
        f"from pydantic import BaseModel\nfrom {module} import {constructor} as check",
    ).replace("AfterValidator(reject)", f"check({argument})")
    if constructor == "WrapValidator":
        source = source.replace("def reject(value):", "def reject(value, handler):")
    assert _check(source) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("", ""),
        ("class Model(BaseModel):", "alias = reject\nclass Model(BaseModel):"),
        (
            "class Model(BaseModel):\n    value: Annotated[int, AfterValidator(reject)]",
            "type Validated = Annotated[int, AfterValidator(reject)]\nclass Model(BaseModel):\n    value: Validated",
        ),
    ],
)
def test_functional_rejection_does_not_hide_an_ordinary_raise(old: str, new: str) -> None:
    source = _FUNCTIONAL_SOURCE.replace(old, new) if old else _FUNCTIONAL_SOURCE
    if old == "class Model(BaseModel):":
        source = source.replace("AfterValidator(reject)", "AfterValidator(alias)")
    assert len(_check(source + "def read(): raise DomainError\n")) == 1


@pytest.mark.parametrize(
    "suffix",
    [
        "reject(1)\n",
        "register(reject)\n",
        "unused = reject\n",
        "class Owner:\n    reject = other\n    def read(self): reject(1)\n",
    ],
)
def test_callback_ordinary_calls_and_unowned_value_uses_still_warn(suffix: str) -> None:
    assert len(_check(_FUNCTIONAL_SOURCE + suffix)) == 1


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("class Model(BaseModel):", "class Model:"),
        ("class Model(BaseModel):", "@custom\nclass Model(BaseModel):"),
        ("class Model(BaseModel):", "class Model(BaseModel):\n    descriptor = Descriptor()"),
        (
            "class Model(BaseModel):",
            "class Model(BaseModel):\n    def __get_pydantic_core_schema__(cls, source, handler): return custom",
        ),
        ("def reject(value):", "async def reject(value):"),
        (
            "def reject(value): raise DomainError('rejected')",
            "def reject(value):\n    yield value\n    raise DomainError",
        ),
        ("def reject(value):", "@custom\ndef reject(value):"),
        ("AfterValidator(reject)", "AfterValidator(reject, unknown=True)"),
        ("AfterValidator(reject)", "AfterValidator(reject, other)"),
        ("from typing import Annotated", "from external import Annotated"),
        (
            "from pydantic import BaseModel, AfterValidator",
            "from pydantic import BaseModel\nfrom external import AfterValidator",
        ),
        ("class DomainError(ValueError):", "AfterValidator = custom\nclass DomainError(ValueError):"),
        ("class DomainError(ValueError):", "class DomainError(Exception):"),
    ],
)
def test_functional_callback_requires_proven_static_rejection_contract(old: str, new: str) -> None:
    assert len(_check(_FUNCTIONAL_SOURCE.replace(old, new))) == 1


@pytest.mark.parametrize("chain", [False, True])
def test_stable_callback_assignment_aliases_preserve_rejection(*, chain: bool) -> None:
    declarations = "alias = reject\nsecond = alias\n" if chain else "alias = reject\n"
    target = "second" if chain else "alias"
    source = _FUNCTIONAL_SOURCE.replace("class Model(BaseModel):", declarations + "class Model(BaseModel):").replace(
        "AfterValidator(reject)", f"AfterValidator({target})"
    )
    assert _check(source) == []
    assert len(_check(source + f"{target}(1)\n")) == 1
    assert len(_check(source + f"register({target})\n")) == 1
    assert len(_check(source + f"{target} = other\n")) == 1
    assert len(_check(source + f"{target}.flag = other\n")) == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_nongeneric_annotation_alias_used_only_by_direct_model_fields(*, legacy: bool) -> None:
    declaration = "Validated: TypeAlias" if legacy else "type Validated"
    source = _FUNCTIONAL_SOURCE.replace(
        "from typing import Annotated", "from typing import Annotated, TypeAlias"
    ).replace(
        "class Model(BaseModel):\n    value: Annotated[int, AfterValidator(reject)]",
        f"{declaration} = Annotated[int, AfterValidator(reject)]\nclass Model(BaseModel):\n    value: Validated",
    )
    assert _check(source) == []
    assert len(_check(source + "register(Validated)\n")) == 1
    assert len(_check(source + "Validated = other\n")) == 1


_NESTED_SOURCE = (
    "from pydantic import field_validator\n"
    "class DomainError(ValueError): pass\n"
    "class Model:\n"
    "    @field_validator('value')\n"
    "    def validate(cls, value):\n"
    "        def reject(): raise DomainError('rejected')\n"
    "        return reject()\n"
)


def test_nonescaping_direct_nested_helper_preserves_rejection() -> None:
    assert _check(_NESTED_SOURCE) == []
    assert len(_check(_NESTED_SOURCE + "def read(): raise DomainError\n")) == 1
    recursive = _NESTED_SOURCE.replace(
        "def reject(): raise DomainError('rejected')",
        "def reject():\n            if again: return reject()\n            raise DomainError",
    )
    assert _check(recursive) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "return reject",
        "return schedule(reject)",
        "alias = reject\n        return alias()",
        "return lambda: reject()",
        "return (reject() for _ in values)",
        "def later(): return reject()\n        return later()",
        "reject = other\n        return reject()",
        "reject.flag = value\n        return reject()",
    ],
)
def test_nested_helper_escape_or_mutation_retains_review(replacement: str) -> None:
    assert len(_check(_NESTED_SOURCE.replace("return reject()", replacement))) == 1


@pytest.mark.parametrize(("depth", "expected"), [(1, 0), (3, 0), (33, 1)])
def test_nested_helper_proof_budget(depth: int, expected: int) -> None:
    lines = [
        "from pydantic import field_validator",
        "class DomainError(ValueError): pass",
        "class Model:",
        "    @field_validator('value')",
        "    def validate(cls, value):",
    ]
    lines.extend(" " * (8 + level * 4) + f"def helper{level}():" for level in range(depth))
    lines.append(" " * (8 + depth * 4) + "raise DomainError")
    lines.extend(" " * (8 + level * 4) + f"return helper{level}()" for level in reversed(range(depth)))
    assert len(_check("\n".join(lines) + "\n")) == expected
