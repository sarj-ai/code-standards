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


@pytest.mark.parametrize(("base", "count"), [("Exception", 1), ("ValueError", 1), ("MissingError", 0)])
def test_literal_message_exception_requires_a_proven_base(base: str, count: int) -> None:
    source = (
        "from external import MissingError\n"
        f"class Unavailable({base}):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__('unavailable')\n"
        "def load():\n    raise Unavailable\n"
    )
    findings = NoCustomControlFlowException().check(Path("app/store.py"), source)
    assert len(findings) == count
    assert all(finding.code == "SARJ542" and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    "initializer",
    [
        "def __init__(self, detail): super().__init__(detail)",
        "def __init__(self): self.detail = 'unavailable'; super().__init__('unavailable')",
        "def __init__(self): super().__init__(make_message())",
        "def __init__(self): notify(); super().__init__('unavailable')",
        "@decorate\n    def __init__(self): super().__init__('unavailable')",
    ],
)
def test_exception_payloads_and_behavior_remain_valid(initializer: str) -> None:
    source = f"class Unavailable(Exception):\n    {initializer}\ndef load():\n    raise Unavailable\n"
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


_PAYLOAD_ERROR = """class Denied(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f'Denied {name}')
"""


@pytest.mark.parametrize(
    "guard",
    [
        "if not allowed:\n        raise Denied(name)",
        "if allowed:\n        return name\n    else:\n        raise Denied(name)",
    ],
)
@pytest.mark.parametrize("definition", ["def", "async def"])
def test_typed_payload_guard_reviews_the_failure_contract(guard: str, definition: str) -> None:
    source = _PAYLOAD_ERROR + f"{definition} load(name: str, allowed: bool) -> str:\n    {guard}\n    return name\n"
    [finding] = NoCustomControlFlowException().check(Path("app/store.py"), source)
    assert finding.code == "SARJ542"
    assert finding.severity is Severity.WARNING
    assert "format the message at the consumer" in finding.message


@pytest.mark.parametrize(
    "initializer",
    [
        "def __init__(self, name: str) -> None:\n        super().__init__(f'Denied {name}')",
        "def __init__(self, name: str) -> None:\n        self.detail = f'Denied {name}'\n        super().__init__(self.detail)",
        "def __init__(self, name: str) -> None:\n        self.name: str = name\n        super().__init__('Denied')",
        "def __init__(self, *, name: str) -> None:\n        self.name = name\n        super().__init__('Denied')",
    ],
)
def test_payload_identity_or_formatting_is_reviewed(initializer: str) -> None:
    source = f"class Denied(Exception):\n    {initializer}\ndef load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name=name)\n    return name\n"
    assert len(NoCustomControlFlowException().check(Path("app/store.py"), source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "raise Denied(name)",
        "if not allowed:\n        raise Denied",
        "if not allowed:\n        raise Denied()",
        "if not allowed:\n        raise Denied(name, name)",
        "if not allowed:\n        raise Denied(unknown=name)",
        "if not allowed:\n        raise Denied(name, name=name)",
        "if not allowed:\n        raise Denied(*values)",
        "if not allowed:\n        raise Denied(**values)",
        "if not allowed:\n        log(); raise Denied(name)",
        "try:\n        if not allowed:\n            raise Denied(name)\n    finally:\n        cleanup()",
        "with transaction():\n        if not allowed:\n            raise Denied(name)",
        "for value in values:\n        if not allowed:\n            raise Denied(name)",
    ],
)
def test_payload_guard_requires_a_closed_observable_contract(body: str) -> None:
    source = _PAYLOAD_ERROR + f"def load(name: str, allowed: bool) -> str:\n    {body}\n    return name\n"
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


@pytest.mark.parametrize(
    "initializer",
    [
        "def __init__(self, name) -> None:\n        self.name = name",
        "def __init__(self, name: str) -> None:\n        self.name = normalize(name)",
        "def __init__(self, name: str) -> None:\n        notify(name)\n        self.name = name",
        "def __init__(self, name: str) -> None:\n        self.name = name\n    def retry(self) -> None:\n        retry()",
        "def __init__(self, *names: str) -> None:\n        self.names = names",
        "@decorate\n    def __init__(self, name: str) -> None:\n        self.name = name",
    ],
)
def test_payload_behavior_and_untyped_contracts_abstain(initializer: str) -> None:
    source = f"class Denied(Exception):\n    {initializer}\ndef load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


@pytest.mark.parametrize("base", ["BaseException", "AssertionError", "RuntimeError", "TypeError"])
def test_payload_control_flow_and_programming_defect_bases_abstain(base: str) -> None:
    source = (
        _PAYLOAD_ERROR.replace("Exception", base)
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


def test_payload_value_error_validator_keeps_framework_rejection() -> None:
    source = (
        "from pydantic import field_validator\n"
        + _PAYLOAD_ERROR.replace("Exception", "ValueError")
        + "@field_validator('name')\ndef load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


@pytest.mark.parametrize(
    ("prefix", "annotation"),
    [
        ("from typing import Never", "Never"),
        ("from typing import NoReturn as Stop", "Stop"),
        ("import typing", "typing.NoReturn"),
        ("from typing import NoReturn", "'NoReturn'"),
        ("from typing import Never", "'Never'"),
    ],
)
def test_payload_never_returning_contract_is_not_an_expected_outcome(prefix: str, annotation: str) -> None:
    source = (
        prefix
        + "\n"
        + _PAYLOAD_ERROR
        + f"def stop(name: str, allowed: bool) -> {annotation}:\n    if not allowed:\n        raise Denied(name)\n    raise RuntimeError\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


def test_payload_generator_preserves_its_iteration_protocol() -> None:
    source = (
        _PAYLOAD_ERROR
        + "def values(name: str, allowed: bool) -> Iterator[str]:\n    if not allowed:\n        raise Denied(name)\n    yield name\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


def test_payload_guard_remains_a_warning_without_a_fix() -> None:
    source = (
        _PAYLOAD_ERROR
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    rule = NoCustomControlFlowException()
    [finding] = rule.check(Path("app/store.py"), source)
    assert finding.severity is Severity.WARNING
    assert finding.fixes == ()
    assert rule.check(Path("app/store.py"), source) == [finding]


@pytest.mark.parametrize(
    ("prefix", "base"),
    [
        ("from unknown import FrameworkBase\n", "FrameworkBase"),
        ("from trio import Cancelled\n", "Cancelled"),
        ("from asyncio import CancelledError\n", "CancelledError"),
        ("class NativeExit(BaseException):\n    pass\n", "NativeExit"),
    ],
)
def test_payload_unknown_and_native_control_flow_bases_remain_opaque(prefix: str, base: str) -> None:
    source = (
        prefix
        + _PAYLOAD_ERROR.replace("Exception", base)
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


def test_payload_positional_only_parameter_cannot_be_supplied_as_a_keyword() -> None:
    source = (
        _PAYLOAD_ERROR.replace("name: str)", "name: str, /)")
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name=name)\n    return name\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


def test_payload_source_resolves_a_first_party_exception_base(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.0'\n")
    (tmp_path / "errors.py").write_text("class DomainError(Exception):\n    pass\n")
    source = (
        "from errors import DomainError\n"
        + _PAYLOAD_ERROR.replace("Exception", "DomainError")
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    [finding] = NoCustomControlFlowException().check(tmp_path / "service.py", source)
    assert finding.code == "SARJ542"


def test_payload_first_party_base_preserves_native_control_flow(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.0'\n")
    (tmp_path / "errors.py").write_text("class DomainError(BaseException):\n    pass\n")
    source = (
        "from errors import DomainError\n"
        + _PAYLOAD_ERROR.replace("Exception", "DomainError")
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    assert NoCustomControlFlowException().check(tmp_path / "service.py", source) == []


@pytest.mark.parametrize("base_use", ["register_handler(Base)", "alias = Base", "Base.code = 400"])
def test_payload_ancestry_preserves_registered_or_mutated_bases(base_use: str) -> None:
    source = (
        "class Base(Exception): pass\n"
        + base_use
        + "\n"
        + _PAYLOAD_ERROR.replace("Exception", "Base")
        + "def load(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Denied(name)\n    return name\n"
    )
    assert NoCustomControlFlowException().check(Path("app/store.py"), source) == []


_IMPORTED_ERROR = "class Rejected(Exception): pass\n"
_IMPORTED_PAYLOAD = "class Rejected(Exception):\n    def __init__(self, name: str) -> None:\n        self.name = name\n        super().__init__(f'Denied {name}')\n"
_IMPORTED_SERVICE = "from errors import Rejected\ndef save(name: str, allowed: bool) -> str:\n    if not allowed:\n        raise Rejected(name)\n    return name\n"


def _imported_project(tmp_path: Path, errors: str = _IMPORTED_ERROR, service: str = _IMPORTED_SERVICE) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n")
    (tmp_path / "errors.py").write_text(errors)
    path = tmp_path / "service.py"
    path.write_text(service)
    return path


@pytest.mark.parametrize("errors", [_IMPORTED_ERROR, _IMPORTED_PAYLOAD, "class Rejected(ValueError): pass\n"])
@pytest.mark.parametrize("definition", ["def", "async def"])
def test_imported_guard(tmp_path: Path, errors: str, definition: str) -> None:
    path = _imported_project(tmp_path, errors, _IMPORTED_SERVICE.replace("def save", f"{definition} save"))
    source = path.read_text()
    [finding] = NoCustomControlFlowException().check(path, source)
    assert finding.line == 4
    assert finding.severity is Severity.WARNING
    assert not finding.fixes
    assert "return contract" in finding.message
    assert "consumer" in finding.message


@pytest.mark.parametrize(
    "prefix",
    [
        "from typing import final",
        "from typing import final as final",
        "from typing_extensions import final",
        "import typing as t",
    ],
)
def test_proven_final_exception(tmp_path: Path, prefix: str) -> None:
    decorator = "t.final" if prefix.startswith("import") else "final"
    path = _imported_project(tmp_path, prefix + "\n@" + decorator + "\n" + _IMPORTED_PAYLOAD)
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1


@pytest.mark.parametrize(
    "errors",
    [
        "from external import final\n@final\n" + _IMPORTED_ERROR,
        "from typing import final\nfinal=other\n@final\n" + _IMPORTED_ERROR,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from typing import final\n@final\n" + _IMPORTED_ERROR,
        "@decorate\n" + _IMPORTED_ERROR,
        "class Rejected(Exception, Other): pass\n",
        "class Rejected[T](Exception): pass\n",
        "class Rejected(Exception, metaclass=Meta): pass\n",
        _IMPORTED_ERROR + "register(Rejected)\n",
        _IMPORTED_ERROR + "alias=Rejected\n",
        _IMPORTED_ERROR + "Rejected.flag=True\n",
        _IMPORTED_ERROR + "del Rejected.flag\n",
        _IMPORTED_ERROR + "Rejected=other\n",
        _IMPORTED_ERROR + "class Rejected(Exception): pass\n",
        "from external import *\n" + _IMPORTED_ERROR,
        _IMPORTED_ERROR + "globals()[name]=value\n",
        "from external import FrameworkError\nclass Rejected(FrameworkError): pass\n",
        "from fastapi import HTTPException\nclass Rejected(HTTPException): pass\n",
        "from asyncio import CancelledError\nclass Rejected(CancelledError): pass\n",
    ],
)
def test_unproven_imported_contracts_abstain(tmp_path: Path, errors: str) -> None:
    path = _imported_project(tmp_path, errors)
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize(
    "base",
    [
        "BaseException",
        "SystemExit",
        "KeyboardInterrupt",
        "GeneratorExit",
        "StopIteration",
        "RuntimeError",
        "AssertionError",
        "TypeError",
        "OSError",
    ],
)
def test_exceptional_and_control_flow_roots(tmp_path: Path, base: str) -> None:
    path = _imported_project(tmp_path, _IMPORTED_ERROR.replace("Exception", base))
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize(
    "body",
    [
        "raise Rejected(name)",
        "if not allowed:\n        log(); raise Rejected(name)",
        "if not allowed:\n        notify()\n        raise Rejected(name)",
        "try:\n        if not allowed:\n            raise Rejected(name)\n    finally:\n        cleanup()",
        "try:\n        work()\n    except ValueError:\n        if not allowed:\n            raise Rejected(name)",
        "with transaction():\n        if not allowed:\n            raise Rejected(name)",
        "async with transaction():\n        if not allowed:\n            raise Rejected(name)",
        "for value in values:\n        if not allowed:\n            raise Rejected(name)",
        "while not allowed:\n        if not allowed:\n            raise Rejected(name)",
        "match allowed:\n        case False:\n            raise Rejected(name)",
        "if not allowed:\n        error=Rejected(name)\n        raise error",
        "if not allowed:\n        message=format_message(name)\n        raise Rejected(message)",
        'if not allowed:\n        message="unused"\n        raise Rejected(name)',
        'if not allowed:\n        message=f"Denied {format_name(name)}"\n        raise Rejected(message)',
    ],
)
def test_new_detection_stays_outside_protected_or_complex_flow(tmp_path: Path, body: str) -> None:
    source = (
        "from errors import Rejected\nasync def save(name: str, allowed: bool) -> str:\n    "
        + body
        + "\n    return name\n"
    )
    path = _imported_project(tmp_path, _IMPORTED_PAYLOAD, source)
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize(
    "source",
    [
        _IMPORTED_SERVICE.replace(
            "def save(name: str, allowed: bool)", "def save(name: str, allowed: bool, Rejected: object)"
        ),
        _IMPORTED_SERVICE.replace("def save", "Rejected=other\ndef save"),
        _IMPORTED_SERVICE + "register(Rejected)\n",
        _IMPORTED_SERVICE + "alias=Rejected\n",
        _IMPORTED_SERVICE + "Rejected.flag=True\n",
        _IMPORTED_SERVICE.replace("from errors import Rejected", "from external import Rejected"),
        _IMPORTED_SERVICE.replace("from errors import Rejected", "import errors").replace(
            "raise Rejected(name)", "raise errors.Rejected(name)"
        ),
        _IMPORTED_SERVICE.replace(
            "from errors import Rejected",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from errors import Rejected",
        ),
        _IMPORTED_SERVICE.replace("from errors import Rejected", "from external import *\nfrom errors import Rejected"),
        _IMPORTED_SERVICE + "exec(code)\n",
        _IMPORTED_SERVICE.replace(" -> str", ""),
        _IMPORTED_SERVICE.replace(" -> str", " -> 'str'"),
        _IMPORTED_SERVICE.replace("def save", "@custom\ndef save"),
        _IMPORTED_SERVICE.replace("def save", '@field_validator("name")\ndef save'),
        _IMPORTED_SERVICE.replace("def save", "def __call__"),
        _IMPORTED_SERVICE.replace("return name", "yield name"),
    ],
    ids=(
        "parameter-shadows-import",
        "rebound-import",
        "registered-import",
        "aliased-import",
        "mutated-import",
        "external-source",
        "module-attribute-raise",
        "type-only-import",
        "wildcard-namespace",
        "dynamic-namespace",
        "missing-return-annotation",
        "quoted-return-annotation",
        "custom-function-decorator",
        "validator-decorator",
        "special-method-contract",
        "generator-contract",
    ),
)
def test_import_and_function_ownership(tmp_path: Path, source: str) -> None:
    path = _imported_project(tmp_path, _IMPORTED_PAYLOAD, source)
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize(
    ("prefix", "annotation"),
    [
        ("from typing import Never", "Never"),
        ("from typing import NoReturn as Stop", "Stop"),
        ("import typing", "typing.NoReturn"),
    ],
)
def test_never_contracts_remain_exceptions(tmp_path: Path, prefix: str, annotation: str) -> None:
    path = _imported_project(
        tmp_path, _IMPORTED_ERROR, prefix + "\n" + _IMPORTED_SERVICE.replace(" -> str", " -> " + annotation)
    )
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize("value", ["'Denied'", "f'Denied {name}'", "f'Denied {name!r}'", "f'Denied {name:>12}'"])
def test_message_preparation_is_still_a_rejection_guard(tmp_path: Path, value: str) -> None:
    source = _IMPORTED_SERVICE.replace("raise Rejected(name)", "message=" + value + "\n        raise Rejected(message)")
    path = _imported_project(tmp_path, _IMPORTED_PAYLOAD, source)
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "Rejected",
        "Rejected()",
        "Rejected(name,name)",
        "Rejected(missing=name)",
        "Rejected(name, name=name)",
        "Rejected(*values)",
        "Rejected(**values)",
    ],
)
def test_imported_payload_arity_is_required(tmp_path: Path, expression: str) -> None:
    path = _imported_project(tmp_path, _IMPORTED_PAYLOAD, _IMPORTED_SERVICE.replace("Rejected(name)", expression))
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


def test_renamed_relative_import_and_per_function_deduplication(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "errors.py").write_text(_IMPORTED_PAYLOAD)
    source = _IMPORTED_SERVICE.replace("from errors import Rejected", "from .errors import Rejected as Denied").replace(
        "raise Rejected", "raise Denied"
    )
    source = source.replace("    return name", "    if allowed is None:\n        raise Denied(name)\n    return name")
    source += "\n" + source[source.index("def save") :].replace("def save", "def read")
    findings = NoCustomControlFlowException().check(package / "service.py", source)
    assert len(findings) == 2
    assert findings[0].line != findings[1].line


def test_source_and_raise_suppressions(tmp_path: Path) -> None:
    path = _imported_project(
        tmp_path, _IMPORTED_ERROR.replace(": pass", ":  # sarj-noqa: SARJ542 -- framework exception contract\n    pass")
    )
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []
    (tmp_path / "errors.py").write_text(_IMPORTED_ERROR)
    assert (
        NoCustomControlFlowException().check(
            path,
            source.replace("raise Rejected(name)", "raise Rejected(name)  # sarj-noqa: SARJ542 -- reviewed boundary"),
        )
        == []
    )


def test_source_resolution_does_not_import_application_modules(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    errors = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n" + _IMPORTED_ERROR
    path = _imported_project(tmp_path, errors)
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1
    assert not marker.exists()


def test_inherited_source_proven_base_without_payload(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text(
        "class DomainError(Exception):\n    def __str__(self) -> str:\n        return str(self.args)\n"
    )
    path = _imported_project(tmp_path, "from base import DomainError\nclass Rejected(DomainError): pass\n")
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1


def test_transaction_has_finished_before_rejection_guard(tmp_path: Path) -> None:
    source = _IMPORTED_SERVICE.replace(
        "    if not allowed:", "    with transaction():\n        work()\n    if not allowed:"
    )
    path = _imported_project(tmp_path, _IMPORTED_ERROR, source)
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1


def test_legitimate_absence_and_existing_return_union(tmp_path: Path) -> None:
    source = _IMPORTED_SERVICE.replace(
        "if not allowed:\n        raise Rejected(name)", "if not allowed:\n        return None"
    ).replace(" -> str:", " -> str | None:")
    path = _imported_project(tmp_path, _IMPORTED_ERROR, source)
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


def test_inherited_constructor_arity_is_not_assumed(tmp_path: Path) -> None:
    errors = _IMPORTED_PAYLOAD.replace("Rejected", "Base") + "class Rejected(Base): pass\n"
    path = _imported_project(tmp_path, errors, _IMPORTED_SERVICE.replace("Rejected(name)", "Rejected()"))
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


def test_suppressed_first_guard_does_not_hide_another_guard(tmp_path: Path) -> None:
    source = _IMPORTED_SERVICE.replace(
        "raise Rejected(name)",
        "raise Rejected(name)  # sarj-noqa: SARJ542 -- reviewed boundary",
    ).replace("    return name", "    if allowed is None:\n        raise Rejected(name)\n    return name")
    path = _imported_project(tmp_path, service=source)
    source = path.read_text()
    [finding] = NoCustomControlFlowException().check(path, source)
    assert finding.line == 6


@pytest.mark.parametrize("expression", ["Rejected", "Rejected()"])
def test_imported_fixed_initializer_accepts_only_its_signature(tmp_path: Path, expression: str) -> None:
    errors = "class Rejected(Exception):\n    def __init__(self) -> None:\n        super().__init__('denied')\n"
    path = _imported_project(tmp_path, errors, _IMPORTED_SERVICE.replace("Rejected(name)", expression))
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1


@pytest.mark.parametrize(
    "expression", ["Rejected(name)", "Rejected(name=name)", "Rejected(*values)", "Rejected(**values)"]
)
def test_imported_fixed_initializer_rejects_unknown_arguments(tmp_path: Path, expression: str) -> None:
    errors = "class Rejected(Exception):\n    def __init__(self) -> None:\n        super().__init__('denied')\n"
    path = _imported_project(tmp_path, errors, _IMPORTED_SERVICE.replace("Rejected(name)", expression))
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize("expression", ["Rejected(reason=name)", "Rejected(*values)", "Rejected(**values)"])
def test_native_marker_call_contract_is_not_invented(tmp_path: Path, expression: str) -> None:
    path = _imported_project(tmp_path, service=_IMPORTED_SERVICE.replace("Rejected(name)", expression))
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize("directory", ["vendor", "vendored", "third_party", "tests", "generated"])
def test_foreign_exception_sources_abstain(tmp_path: Path, directory: str) -> None:
    path = _imported_project(tmp_path)
    source = path.read_text()
    foreign = tmp_path / directory
    foreign.mkdir()
    (foreign / "__init__.py").write_text("")
    (foreign / "errors.py").write_text(_IMPORTED_ERROR)
    source = source.replace("from errors import", f"from {directory}.errors import")
    assert NoCustomControlFlowException().check(path, source) == []


def test_reexported_exception_is_not_assumed_to_be_a_local_class(tmp_path: Path) -> None:
    path = _imported_project(tmp_path, "from implementation import Rejected\n")
    source = path.read_text()
    (tmp_path / "implementation.py").write_text(_IMPORTED_ERROR)
    assert NoCustomControlFlowException().check(path, source) == []


def test_different_import_aliases_share_one_function_contract_warning(tmp_path: Path) -> None:
    path = _imported_project(tmp_path)
    source = path.read_text()
    source = source.replace(
        "from errors import Rejected", "from errors import Rejected\nfrom errors import Rejected as Other"
    )
    source = source.replace("    return name", "    if allowed is None:\n        raise Other(name)\n    return name")
    assert len(NoCustomControlFlowException().check(path, source)) == 1


def test_local_payload_message_guard_and_final_marker() -> None:
    source = "from typing import final\n@final\n" + _IMPORTED_PAYLOAD
    source += _IMPORTED_SERVICE.removeprefix("from errors import Rejected\n").replace(
        "raise Rejected(name)",
        'message=f"Denied {name}"\n        raise Rejected(message)',
    )
    assert len(_check(source)) == 1


def test_cross_module_custom_allocator_abstains(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text(
        "class Base(Exception):\n    def __new__(cls, token: str):\n        return super().__new__(cls)\n"
    )
    path = _imported_project(tmp_path, "from base import Base\n" + _IMPORTED_PAYLOAD.replace("Exception", "Base"))
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize(("depth", "count"), [(1, 1), (7, 1), (8, 0), (9, 0)])
def test_imported_ancestry_proof_is_bounded(tmp_path: Path, depth: int, count: int) -> None:
    declarations = ["class Base(Exception): pass"]
    parent = "Base"
    for index in range(depth):
        name = f"Parent{index}"
        declarations.append(f"class {name}({parent}): pass")
        parent = name
    declarations.append(f"class Rejected({parent}): pass")
    path = _imported_project(tmp_path, "\n".join(declarations) + "\n")
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == count


def test_imported_definition_module_budget(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n")
    imports: list[str] = []
    functions: list[str] = []
    for index in range(33):
        (tmp_path / f"errors_{index}.py").write_text(_IMPORTED_ERROR)
        imports.append(f"from errors_{index} import Rejected as Rejected{index}")
        functions.append(
            f'def save{index}(allowed: bool) -> str:\n    if not allowed:\n        raise Rejected{index}\n    return "saved"\n'
        )
    findings = NoCustomControlFlowException().check(tmp_path / "service.py", "\n".join([*imports, *functions]))
    assert len(findings) == 32
    assert len({(finding.line, finding.col) for finding in findings}) == 32


def test_imported_functional_validator_callback_preserves_rejection(tmp_path: Path) -> None:
    source = "from typing import Annotated\nfrom pydantic import BaseModel, AfterValidator\nfrom errors import Rejected\ndef reject(value: str) -> str:\n    if not value:\n        raise Rejected('empty')\n    return value\nclass Model(BaseModel):\n    name: Annotated[str, AfterValidator(reject)]\n"
    path = _imported_project(tmp_path, _IMPORTED_ERROR.replace("Exception", "ValueError"), source)
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []
    assert len(NoCustomControlFlowException().check(path, source + '\nreject("ordinary")\n')) == 1


def test_imported_scope_identity_is_independent_of_error_spelling(tmp_path: Path) -> None:
    path = _imported_project(
        tmp_path, _IMPORTED_ERROR.replace("Rejected", "Signal"), _IMPORTED_SERVICE.replace("Rejected", "Signal")
    )
    source = path.read_text()
    assert len(NoCustomControlFlowException().check(path, source)) == 1


def test_quoted_or_missing_imported_definition_abstains(tmp_path: Path) -> None:
    path = _imported_project(tmp_path, "class Rejected(Exception):\n    (\n")
    source = path.read_text()
    assert NoCustomControlFlowException().check(path, source) == []
    (tmp_path / "errors.py").unlink()
    assert NoCustomControlFlowException().check(path, source) == []


@pytest.mark.parametrize("base", ["ValueError", "Exception"])
def test_source_proven_imported_validator_ancestry(tmp_path: Path, base: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.0.0"\n')
    (tmp_path / "base.py").write_text(f"class Parent({base}): pass\n")
    source = 'from base import Parent\nfrom pydantic import field_validator\nclass LocalRejected(Parent): pass\nclass Model:\n    @field_validator("value")\n    def validate(cls, value: str) -> str:\n        raise LocalRejected("invalid")\n'
    path = tmp_path / "model.py"
    assert len(NoCustomControlFlowException().check(path, source)) == (0 if base == "ValueError" else 1)
    assert (
        len(
            NoCustomControlFlowException().check(
                path, source + '\ndef read() -> str:\n    raise LocalRejected("invalid")\n'
            )
        )
        == 1
    )


def test_value_error_ancestor_behavior_does_not_erase_validator_protocol() -> None:
    source = 'from pydantic import field_validator\nclass Parent(ValueError):\n    def __str__(self) -> str:\n        return "invalid"\nclass LocalRejected(Parent): pass\nclass Model:\n    @field_validator("value")\n    def validate(cls, value: str) -> str:\n        raise LocalRejected("invalid")\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "declarations",
    [
        "from typing import Never\ntype Stop = Never",
        "from typing import NoReturn,TypeAlias\nStop: TypeAlias = NoReturn",
        "from typing import Never\ntype Halt = Never\ntype Stop = Halt",
    ],
)
def test_module_never_alias_keeps_nonreturning_contract(tmp_path: Path, declarations: str) -> None:
    source = declarations + "\n" + _IMPORTED_SERVICE.replace(" -> str", " -> Stop")
    path = _imported_project(tmp_path, service=source)
    assert NoCustomControlFlowException().check(path, path.read_text()) == []


def test_private_function_name_does_not_imply_native_control_flow(tmp_path: Path) -> None:
    path = _imported_project(tmp_path, service=_IMPORTED_SERVICE.replace("def save", "def __save"))
    assert len(NoCustomControlFlowException().check(path, path.read_text())) == 1


def test_inherited_registration_hook_ends_constructor_proof(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text(
        "registered: list[type[Exception]] = []\nclass Base(Exception):\n"
        "    def __init_subclass__(cls) -> None:\n        registered.append(cls)\n"
    )
    errors = "from base import Base\nclass Rejected(Base): pass\n"
    path = _imported_project(tmp_path, errors)
    assert NoCustomControlFlowException().check(path, path.read_text()) == []
    local = "from base import Base\n" + _IMPORTED_PAYLOAD.replace("Exception", "Base")
    local += _IMPORTED_SERVICE.removeprefix("from errors import Rejected\n")
    assert NoCustomControlFlowException().check(path, local) == []
