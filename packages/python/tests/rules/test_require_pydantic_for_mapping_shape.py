from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import RequirePydanticForMappingShape


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/claims.py"):
    return RequirePydanticForMappingShape().check(Path(path), dedent(source))


@pytest.mark.parametrize(
    "example",
    RequirePydanticForMappingShape.public_examples(),
    ids=[example.example_id for example in RequirePydanticForMappingShape.public_examples()],
)
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source)) == example.expected_count


@pytest.mark.parametrize(
    "body",
    [
        "return isinstance(raw.get('flag'), bool)",
        "return isinstance(raw['flag'], bool)",
        "return raw.get('kind') == 'event'",
        "return raw.get('kind') in {'event', 'request'}",
        "return type(raw.get('flag')) is bool",
        "if raw.get('flag'):\n    return True",
        "return True if raw.get('flag') else False",
        "assert not raw.get('flag')",
        "value = raw.get('flag')\nreturn isinstance(value, bool)",
        "value = raw['kind']\nalias = value\nreturn alias == 'event'",
        "alias = raw\nreturn isinstance(alias.get('flag'), bool)",
        "alias: dict[str, object] = raw\nreturn isinstance(alias['flag'], bool)",
        "return isinstance((value := raw.get('flag')), bool)",
        "match raw.get('value'):\n    case str(value):\n        return value",
        "match raw.get('value'):\n    case {'nested': int()}:\n        return True",
        "match raw.get('value'):\n    case 'x' | 'y':\n        return True",
        "match raw.get('value'):\n    case [int(), int()]:\n        return True",
        "match claim, raw.get('factor_age'):\n    case 'factor', [int(), int(age)] if not isinstance(age, bool):\n        return age >= 0\n    case _:\n        return False",
    ],
)
def test_detects_field_shape_and_discriminator_probes(body: str) -> None:
    source = "def verified(raw: dict[str, object], claim=None):\n" + "\n".join(
        "    " + line for line in body.splitlines()
    )
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    ("prefix", "annotation"),
    [
        ("", "'dict[str, object]'"),
        ("from typing import Any", "dict[str, Any]"),
        ("from typing import Any as Unknown", "dict[str, Unknown]"),
        ("from pydantic import JsonValue", "dict[str, JsonValue]"),
        ("from collections.abc import Mapping", "Mapping[str, object]"),
        ("import collections.abc as abc", "abc.Mapping[str, object]"),
        ("from typing import Dict", "Dict[str, object]"),
        ("from typing import Annotated", "Annotated[dict[str, object], 'raw']"),
        ("from typing import Optional", "Optional[dict[str, object]]"),
        ("", "dict[str, object] | None"),
        ("type Raw = dict[str, object]", "Raw"),
        ("from typing import TypeAlias\nRaw: TypeAlias = dict[str, object]", "Raw"),
        ("type Value = object\ntype Raw = dict[str, Value]", "Raw"),
    ],
)
def test_resolves_opaque_mapping_annotations(prefix: str, annotation: str) -> None:
    assert len(_check(f"{prefix}\ndef verified(raw: {annotation}):\n    return isinstance(raw.get('flag'), bool)")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def f(raw: dict[str, object]):\n    return raw.get('flag')",
        "def f(raw: dict[str, object]):\n    return consume(raw)",
        "def f(raw: dict[str, object], key: str):\n    return isinstance(raw.get(key), bool)",
        "def f(raw: dict[str, bool]):\n    return isinstance(raw.get('flag'), bool)",
        "def f(raw: dict[str, str | int]):\n    return raw.get('kind') == 'event'",
        "def f(raw: dict[object, object]):\n    return isinstance(raw.get('flag'), bool)",
        "def f(raw: dict[str, list[object]]):\n    return isinstance(raw.get('flag'), list)",
        "def f(raw):\n    return isinstance(raw.get('flag'), bool)",
        "def f(value: object):\n    return isinstance(value, bool)",
        "def f(raw: dict[str, object]):\n    raw = other\n    return isinstance(raw.get('flag'), bool)",
        "def f(raw: dict[str, object]):\n    value = raw.get('flag')\n    value = other\n    return isinstance(value, bool)",
        "def f(raw: dict[str, object]):\n    return isinstance(transform(raw.get('flag')), bool)",
        "def f(raw: dict[str, object]):\n    match raw.get('flag'):\n        case value:\n            return value",
        "def f(raw: dict[str, object], claim):\n    match claim, raw.get('flag'):\n        case 'known', value:\n            return value",
        "class dict: pass\ndef f(raw: dict[str, object]):\n    return isinstance(raw.get('flag'), bool)",
        "class object: pass\ndef f(raw: dict[str, object]):\n    return isinstance(raw.get('flag'), bool)",
        "def f(raw: dict[str, object], isinstance):\n    return isinstance(raw.get('flag'), bool)",
        "def f(raw: dict[str, object], str):\n    return isinstance(raw.get('flag'), bool)",
        "from custom import Mapping\ndef f(raw: Mapping[str, object]):\n    return isinstance(raw.get('flag'), bool)",
        "from typing import Any\ndef f(raw: dict[str, Any], Any):\n    return isinstance(raw.get('flag'), bool)",
        "type Raw = dict[str, object]\nRaw = Custom\ndef f(raw: Raw):\n    return isinstance(raw.get('flag'), bool)",
        "type Raw = Raw\ndef f(raw: Raw):\n    return isinstance(raw.get('flag'), bool)",
        "def f(raw: dict[str, object]):\n    raw['flag'] = True",
        "# isinstance(raw.get('flag'), bool)\ntext = 'dict[str, object]'",
    ],
)
def test_preserves_non_parsing_and_ambiguous_cases(source: str) -> None:
    assert _check(source) == []


def test_locals_aliases_and_repeated_uses_report_original_read_once() -> None:
    findings = _check("""
        def f(data):
            raw: dict[str, object] = data
            alias = raw
            value = alias.get('flag')
            if isinstance(value, bool):
                return value is True
            return value is None
    """)
    assert len(findings) == 1
    assert findings[0].line == 5


@pytest.mark.parametrize("mode", ["before", "wrap"])
@pytest.mark.parametrize("decorator", ["field_validator", "model_validator"])
@pytest.mark.parametrize("module", ["pydantic", "pydantic.functional_validators"])
def test_pydantic_raw_validator_boundary_is_preserved(mode: str, decorator: str, module: str) -> None:
    source = f"""
        from pydantic import BaseModel
        from {module} import {decorator}
        class Model(BaseModel):
            value: str
            @{decorator}(mode='{mode}')
            @classmethod
            def normalize(cls, raw: dict[str, object]):
                return raw.get('kind') == 'event'
    """
    assert _check(source) == []


@pytest.mark.parametrize("module", ["pydantic", "pydantic.types"])
@pytest.mark.parametrize(
    "registration", ["Discriminator(choose)", "Discriminator(discriminator=choose)", "Discriminator(alias)"]
)
def test_callable_discriminator_raw_boundary_is_preserved(module: str, registration: str) -> None:
    assert (
        _check(f"""
        from {module} import Discriminator
        def choose(raw: dict[str, object]):
            if raw.get('kind') == 'event':
                return 'event'
            return None
        alias = choose
        discriminator = {registration}
    """)
        == []
    )


def test_same_named_non_pydantic_decorator_does_not_hide_probe() -> None:
    assert (
        len(
            _check("""
        from custom import model_validator
        @model_validator(mode='before')
        def f(raw: dict[str, object]):
            return isinstance(raw.get('flag'), bool)
    """)
        )
        == 1
    )


@pytest.mark.parametrize("module", ["pydantic", "pydantic.functional_validators", "custom"])
@pytest.mark.parametrize("metadata", ["BeforeValidator", "WrapValidator"])
@pytest.mark.parametrize("registration", ["Validator(normalize)", "Validator(func=normalize)", "Validator(alias)"])
def test_raw_metadata_callbacks_are_recognized_by_origin(module: str, metadata: str, registration: str) -> None:
    signature = ", handler" if metadata == "WrapValidator" else ""
    result = "handler(value)" if metadata == "WrapValidator" else "value"
    source = f"""
        from typing import Annotated
        from {module} import {metadata} as Validator
        def normalize(raw: dict[str, object]{signature}):
            value = raw.get('name')
            if isinstance(value, str):
                return {result}
            raise ValueError('name is required')
        alias = normalize
        Name = Annotated[str, {registration}]
    """
    assert len(_check(source)) == (1 if module == "custom" else 0)


_CALLABLE_CLASS = """
from pydantic import Discriminator
class Choose:
    __name__ = 'choose'
    def __call__(self, raw: dict[str, object]):
        value = raw.get('kind')
        return value if isinstance(value, str) else None
choose = Choose()
alias = choose
"""


@pytest.mark.parametrize(
    "argument", ["Choose()", "choose", "alias", "choose.__call__", "alias.__call__", "Choose().__call__"]
)
def test_registered_local_callable_discriminator_owns_its_raw_input(argument: str) -> None:
    assert _check(_CALLABLE_CLASS + f"discriminator = Discriminator({argument})") == []


@pytest.mark.parametrize(
    "change",
    [
        "class Choose:",
        "class Choose(External):",
        "class Choose(metaclass=External):",
        "@external\nclass Choose:",
        "class Choose:\n    def __init__(self): pass",
        "class Choose:\n    def __new__(cls): return other",
        "class Choose:\n    def __getattribute__(self, name): return other",
        "class Choose:\n    __call__ = other",
        "class Choose:\n    __init__ = None",
        "class Choose:\n    __slots__ = '__call__'",
    ],
)
def test_ambiguous_callable_class_ownership_does_not_hide_probe(change: str) -> None:
    source = _CALLABLE_CLASS.replace("class Choose:", change)
    if change == "class Choose:":
        source = source.replace("    def __call__", "    @external\n    def __call__")
    assert len(_check(source + "discriminator = Discriminator(choose)")) == 1


@pytest.mark.parametrize(
    "change",
    [
        "Choose = External",
        "Choose.__call__ = other",
        "choose = external",
        "choose.__call__ = other",
        "from elsewhere import Choose",
        "from elsewhere import choose",
    ],
)
def test_rebound_or_directly_mutated_callable_contracts_do_not_hide_probe(change: str) -> None:
    assert len(_check(_CALLABLE_CLASS + change + "\ndiscriminator = Discriminator(choose)")) == 1


def test_same_named_discriminator_and_unregistered_callable_stay_reportable() -> None:
    assert len(_check(_CALLABLE_CLASS)) == 1
    assert (
        len(_check(_CALLABLE_CLASS.replace("from pydantic", "from custom") + "discriminator = Discriminator(choose)"))
        == 1
    )


def test_authored_tests_are_checked_and_exact_suppression_is_honored() -> None:
    source = "def f(raw: dict[str, object]):\n    return isinstance(raw.get('flag'), bool)"
    assert len(_check(source, "tests/test_claims.py")) == 1
    assert _check(f"{source}  # sarj-noqa: SARJ521 -- callback compatibility") == []
    assert len(_check(f"{source}  # sarj-noqa: SARJ411 -- unrelated")) == 1


@pytest.mark.parametrize("assertion", ["assert raw['version'] == 1", "assert isinstance(raw.get('version'), int)"])
def test_asserted_test_oracles_do_not_require_an_input_parser(assertion: str) -> None:
    source = f"def test_result(raw: dict[str, object]):\n    {assertion}"
    assert _check(source, "tests/test_claims.py") == []
    assert len(_check(source)) == 1


def test_vendor_and_generated_sources_are_skipped() -> None:
    source = "def f(raw: dict[str, object]):\n    return isinstance(raw.get('flag'), bool)"
    assert _check(source, "vendor/claims.py") == []
    assert _check(f"# @generated\n{source}") == []
