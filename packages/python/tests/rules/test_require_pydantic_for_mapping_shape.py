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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from functools import partial\nfrom typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\ndef normalize(raw: dict[str, object], *, prefix: str) -> str:\n    value = raw.get('name')\n    if isinstance(value, str):\n        return prefix + value.strip()\n    raise ValueError('string name required')\nName = Annotated[str, BeforeValidator(partial(normalize, prefix='x:'))]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="before-validator-partial-keyword-adapter",
        ),
        pytest.param(
            "from functools import partial\nfrom typing import Annotated\nfrom pydantic import BaseModel, WrapValidator, ValidationError\ndef normalize(raw: dict[str, object], handler, *, prefix: str) -> str:\n    value = raw.get('name')\n    if isinstance(value, str):\n        return handler(prefix + value.strip())\n    raise ValueError('string name required')\nName = Annotated[str, WrapValidator(partial(normalize, prefix='x:'))]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="wrap-validator-partial-keyword-adapter",
        ),
        pytest.param(
            "from functools import partial as bind\nfrom typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\ndef normalize(raw: dict[str, object], *, prefix: str, strip: bool) -> str:\n    value = raw.get('name')\n    if isinstance(value, str):\n        return prefix + (value.strip() if strip else value)\n    raise ValueError('string name required')\nfirst = bind(normalize, prefix='x:')\nconfigured = bind(first, strip=True)\nName = Annotated[str, BeforeValidator(configured)]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="stable-nested-partial-alias-before-adapter",
        ),
        pytest.param(
            "from typing import Final, Literal\nfrom pydantic import BaseModel, ValidationError, model_validator\nMODE: Final[Literal['before']] = 'before'\nclass Model(BaseModel):\n    name: str\n    @model_validator(mode=MODE)\n    @classmethod\n    def normalize(cls, raw: dict[str, object]):\n        value = raw.get('name')\n        if isinstance(value, str):\n            return {'name': value.strip()}\n        raise ValueError('string name required')\nassert Model.model_validate({'name': ' Ada '}).name == 'Ada'\ntry:\n    Model.model_validate({'name': 3})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="module-final-literal-model-before-mode",
        ),
        pytest.param(
            "from typing import ClassVar, Literal\nfrom pydantic import BaseModel, ValidationError, model_validator\nclass Model(BaseModel):\n    MODE: ClassVar[Literal['wrap']] = 'wrap'\n    name: str\n    @model_validator(mode=MODE)\n    @classmethod\n    def normalize(cls, raw: dict[str, object], handler):\n        value = raw.get('name')\n        if isinstance(value, str):\n            return handler({'name': value.strip()})\n        raise ValueError('string name required')\nassert Model.model_validate({'name': ' Ada '}).name == 'Ada'\ntry:\n    Model.model_validate({'name': 3})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="class-local-literal-model-wrap-mode",
        ),
        pytest.param(
            "from pydantic import BaseModel, ValidationError, field_validator\nBEFORE = 'before'\nMODE = BEFORE\nclass Model(BaseModel):\n    name: str\n    @field_validator('name', mode=MODE)\n    @classmethod\n    def normalize(cls, raw: dict[str, object]):\n        value = raw.get('name')\n        if isinstance(value, str):\n            return value.strip()\n        raise ValueError('string name required')\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="stable-mode-alias-chain-field-before",
        ),
        pytest.param(
            "from typing import Final, Literal\nfrom pydantic import BaseModel, ValidationError, field_validator\nMODE: Final[Literal['after']] = 'after'\nclass Model(BaseModel):\n    data: dict[str, object]\n    @field_validator('data', mode=MODE)\n    @classmethod\n    def verify(cls, raw: dict[str, object]):\n        value = raw.get('name')\n        if isinstance(value, str):\n            return raw\n        raise ValueError('string name required')\nassert Model.model_validate({'data': {'name': 'Ada'}}).data == {'name': 'Ada'}\ntry:\n    Model.model_validate({'data': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            1,
            id="after-mode-constant-remains-shape-candidate",
        ),
        pytest.param(
            "from typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\nclass Normalizer:\n    def convert(self, raw: dict[str, object]) -> str:\n        value = raw.get('name')\n        if isinstance(value, str):\n            return 'x:' + value.strip()\n        raise ValueError('string name required')\nnormalizer = Normalizer()\nName = Annotated[str, BeforeValidator(normalizer.convert)]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="registered-bound-instance-before-method",
        ),
        pytest.param(
            "from typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\nclass Normalizer:\n    @staticmethod\n    def convert(raw: dict[str, object]) -> str:\n        value = raw.get('name')\n        if isinstance(value, str):\n            return 'x:' + value.strip()\n        raise ValueError('string name required')\nName = Annotated[str, BeforeValidator(Normalizer.convert)]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="registered-static-before-method",
        ),
        pytest.param(
            "from typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\nclass Normalizer:\n    @classmethod\n    def convert(cls, raw: dict[str, object]) -> str:\n        value = raw.get('name')\n        if isinstance(value, str):\n            return 'x:' + value.strip()\n        raise ValueError('string name required')\nName = Annotated[str, BeforeValidator(Normalizer.convert)]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="registered-class-before-method",
        ),
        pytest.param(
            "from typing import Annotated, final\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\n@final\nclass Normalizer:\n    def __call__(self, raw: dict[str, object]) -> str:\n        value = raw.get('name')\n        if isinstance(value, str):\n            return 'x:' + value.strip()\n        raise ValueError('string name required')\nName = Annotated[str, BeforeValidator(Normalizer())]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="typing-final-callable-before-instance",
        ),
        pytest.param(
            "from typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator, ValidationError\nclass Normalizer:\n    __slots__ = ()\n    def __call__(self, raw: dict[str, object]) -> str:\n        value = raw.get('name')\n        if isinstance(value, str):\n            return 'x:' + value.strip()\n        raise ValueError('string name required')\nName = Annotated[str, BeforeValidator(Normalizer())]\n\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == 'x:Ada'\ntry:\n    Model.model_validate({'name': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            0,
            id="empty-slots-callable-before-instance",
        ),
        pytest.param(
            "from collections.abc import Callable\nfrom pydantic import BaseModel, model_validator\nhandlers: list[Callable[[dict[str, object]], bool]] = []\nclass Model(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, raw: dict[str, object]):\n        def is_named(candidate: dict[str, object]) -> bool:\n            return isinstance(candidate.get('name'), str)\n        handlers.append(is_named)\n        return raw\nassert Model.model_validate({'name': 'Ada'}).name == 'Ada'\nassert handlers[0]({'name': 'Ada'}) is True\nassert handlers[0]({'name': 3}) is False\n",
            1,
            id="escaped-nested-helper-does-not-inherit-raw-ownership",
        ),
        pytest.param(
            "from functools import partial\nfrom typing import Annotated\nfrom pydantic import BaseModel, BeforeValidator\ncalls = []\ndef normalize(raw: dict[str, object], *, prefix: str) -> str:\n    calls.append('called')\n    value = raw.get('name')\n    if isinstance(value, str):\n        return prefix + value.strip()\n    raise ValueError('string name required')\ndef partial(function, **kwargs):\n    return lambda raw: raw\nName = Annotated[dict[str, object], BeforeValidator(partial(normalize, prefix='x:'))]\nclass Model(BaseModel):\n    name: Name\nassert Model.model_validate({'name': {'name': ' Ada '}}).name == {'name': ' Ada '}\nassert calls == []\n",
            1,
            id="shadowed-partial-does-not-prove-callback-ownership",
        ),
        pytest.param(
            "from typing import ClassVar, Literal\nfrom pydantic import BaseModel, ValidationError, field_validator\nMODE = 'before'\nclass Model(BaseModel):\n    MODE: ClassVar[Literal['after']] = 'after'\n    data: dict[str, object]\n    @field_validator('data', mode=MODE)\n    @classmethod\n    def verify(cls, raw: dict[str, object]):\n        value = raw.get('name')\n        if isinstance(value, str):\n            return raw\n        raise ValueError('string name required')\nassert Model.model_validate({'data': {'name': 'Ada'}}).data == {'name': 'Ada'}\ntry:\n    Model.model_validate({'data': {'name': 3}})\nexcept ValidationError:\n    pass\nelse:\n    raise AssertionError('non-string name must be rejected')\n",
            1,
            id="class-mode-shadow-does-not-inherit-global-before",
        ),
    ],
)
def test_registered_raw_callback_ownership_and_lexical_decoys(source: str, expected: int) -> None:
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('def f[object](raw: dict[str, object]):\n    return isinstance(raw.get("flag"), bool)\n', 0),
        (
            'class Service[object]:\n    def f(self, raw: dict[str, object]):\n        return isinstance(raw.get("flag"), bool)\n',
            0,
        ),
        ('def f[str](raw: dict[str, object]):\n    return isinstance(raw.get("flag"), bool)\n', 0),
        ('from typing import Any\ndef f[Any](raw: dict[str, Any]):\n    return isinstance(raw.get("flag"), bool)\n', 0),
        (
            'def outer[object]():\n    def f(raw: dict[str, object]):\n        return isinstance(raw.get("flag"), bool)\n    return f\n',
            0,
        ),
        ('type Raw = dict[str, object]\ndef f[Raw](raw: Raw):\n    return isinstance(raw.get("flag"), bool)\n', 0),
        ('def f[T](raw: dict[str, object]):\n    return isinstance(raw.get("flag"), bool)\n', 1),
        (
            'from typing import Annotated\ndef f[Any](raw: Annotated[dict[str, object], Any]):\n    return isinstance(raw.get("flag"), bool)\n',
            1,
        ),
        (
            'from typing import Annotated, Any\ndef f[object](raw: Annotated[dict[str, Any], object]):\n    return isinstance(raw.get("flag"), bool)\n',
            1,
        ),
        (
            'def f[object](raw: dict[str, object]):\n    return isinstance(raw.get("flag"), bool)\ndef g(raw: dict[str, object]):\n    return isinstance(raw.get("flag"), bool)\n',
            1,
        ),
        (
            'def outer(raw: dict[str, object]):\n    def inner[isinstance](value=isinstance(raw.get("flag"), bool)):\n        return value\n    return inner\n',
            1,
        ),
        (
            'from pydantic import BaseModel, model_validator\nclass Model(BaseModel):\n    @model_validator(mode="before")\n    @classmethod\n    def normalize[model_validator](cls, raw: dict[str, object]):\n        return raw if isinstance(raw.get("flag"), bool) else {}\n',
            0,
        ),
    ],
)
def test_generic_type_parameters_preserve_lexical_annotation_and_runtime_origins(source: str, expected: int) -> None:
    assert len(_check(source)) == expected


@pytest.mark.parametrize("escape", ["return helper", "handlers.append(helper)", "alias = helper\n    return alias"])
def test_nested_helpers_require_nonescaping_adapter_ownership(escape: str) -> None:
    source = """
from pydantic import BeforeValidator
handlers = []
def normalize(raw: dict[str, object]):
    def helper(candidate: dict[str, object]):
        return isinstance(candidate.get('flag'), bool)
    ESCAPE
adapter = BeforeValidator(normalize)
""".replace("ESCAPE", escape)
    assert len(_check(source)) == 1


def test_local_helper_called_only_inside_raw_adapter_inherits_ownership() -> None:
    assert (
        _check("""
from pydantic import BeforeValidator
def normalize(raw: dict[str, object]):
    def helper(candidate: dict[str, object]):
        return isinstance(candidate.get('flag'), bool)
    return helper(raw)
adapter = BeforeValidator(normalize)
""")
        == []
    )


@pytest.mark.parametrize(
    "registration",
    [
        "partial(normalize, raw={})",
        "partial(normalize, {}, strip=True)",
        "partial(normalize, **configuration)",
    ],
)
def test_partial_cannot_bind_or_obscure_the_raw_parameter(registration: str) -> None:
    source = f"""
from functools import partial
from pydantic import BeforeValidator
configuration = {{'strip': True}}
def normalize(raw: dict[str, object], *, strip: bool):
    return isinstance(raw.get('flag'), bool)
adapter = BeforeValidator({registration})
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "change", ["Normalizer.convert = unknown", "instance.convert = unknown", "Normalizer = unknown"]
)
def test_registered_method_mutation_invalidates_callback_ownership(change: str) -> None:
    source = f"""
from pydantic import BeforeValidator
class Normalizer:
    def convert(self, raw: dict[str, object]):
        return isinstance(raw.get('flag'), bool)
instance = Normalizer()
{change}
adapter = BeforeValidator(instance.convert)
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "declaration", ["class Normalizer:\n    MODE = 'after'", "MODE = 'before'\nMODE = 'after'\nclass Normalizer:"]
)
def test_ambiguous_and_shadowed_modes_do_not_create_raw_ownership(declaration: str) -> None:
    source = f"""
from pydantic import field_validator
MODE = 'before'
{declaration}
    @field_validator('data', mode=MODE)
    @classmethod
    def normalize(cls, raw: dict[str, object]):
        return isinstance(raw.get('flag'), bool)
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("shadow", ["convert = None", "convert: object = None"])
def test_class_body_cannot_overwrite_a_registered_method(shadow: str) -> None:
    assert (
        len(
            _check(f"""
from pydantic import BeforeValidator
class Normalizer:
    def convert(self, raw: dict[str, object]):
        return isinstance(raw.get('flag'), bool)
    {shadow}
instance = Normalizer()
adapter = BeforeValidator(instance.convert)
""")
        )
        == 1
    )


def test_partial_requires_an_unbound_positional_input() -> None:
    assert (
        len(
            _check("""
from functools import partial
from pydantic import BeforeValidator
def normalize(*, raw: dict[str, object]):
    return isinstance(raw.get('flag'), bool)
adapter = BeforeValidator(partial(normalize, raw={}))
""")
        )
        == 1
    )
