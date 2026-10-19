from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_any_mapping_types import NoAnyMappingTypes


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/models.py") -> list[Diagnostic]:
    return NoAnyMappingTypes().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    NoAnyMappingTypes.public_examples(),
    ids=[example.example_id for example in NoAnyMappingTypes.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    "annotation",
    [
        "dict[str, Any]",
        "Mapping[str, Any]",
        "list[dict[str, list[Any]]]",
        "dict[str, Any] | None",
        "'dict[str, Any]'",
    ],
)
def test_flags_any_mappings_in_all_annotation_positions(annotation: str) -> None:
    source = f"from typing import Any, Mapping\nvalue: {annotation}\ndef use(arg: {annotation}) -> {annotation}: ...\n"

    assert len(_check(source, "tests/test_models.py")) == 3


@pytest.mark.parametrize(
    "source",
    [
        "value: JsonValue\n",
        "value: object\n",
        "value: dict[str, object]\n",
        "from collections.abc import Mapping\nvalue: Mapping[str, object]\n",
        "def use(value: Payload) -> Result: ...\n",
        "class object: ...\nvalue: object\n",
        "from vendor import Any\nvalue: dict[str, Any]\n",
    ],
)
def test_allows_named_precise_opaque_or_unproven_types(source: str) -> None:
    assert _check(source) == []


def test_exact_suppression_is_honored() -> None:
    assert _check("from typing import Any\nvalue: dict[str, Any]  # sarj-noqa: SARJ447 — raw boundary\n") == []


@pytest.mark.parametrize("path", ["generated/client.py", "vendor/client.py", "third_party/client.py"])
def test_skips_generated_and_vendor_sources(path: str) -> None:
    assert _check("from typing import Any\nvalue: dict[str, Any]\n", path) == []


def test_flags_explicit_alias_chains_but_not_plain_assignments() -> None:
    source = """
from typing import Any, TypeAlias
Leaf: TypeAlias = list[Any]
Payload: TypeAlias = Leaf | None
value: dict[str, Payload]
Plain = Any
other: dict[str, Plain]
"""
    assert len(_check(source)) == 1


def test_flags_unambiguous_implicit_mapping_alias_used_in_function_annotations() -> None:
    source = "from typing import Any\nRow = dict[str, Any]\ndef read() -> Row: ...\n"

    findings = _check(source)

    assert [(finding.line, finding.code) for finding in findings] == [(2, "SARJ447")]


def test_flags_implicit_mapping_alias_used_in_string_annotation() -> None:
    source = "from typing import Any\nRow = dict[str, Any]\ndef read() -> 'Row': ...\n"

    assert [(finding.line, finding.code) for finding in _check(source)] == [(2, "SARJ447")]


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any\nRow = dict[str, Any]\nvalue = Row()\n",
        "from typing import Any\nRow = dict[str, Any]\nRow = dict[str, object]\ndef read() -> Row: ...\n",
        "from typing import Any\nRow = dict[str, Any]\nif enabled:\n    Row = dict[str, object]\ndef read() -> Row: ...\n",
        "from typing import Any\nif enabled:\n    Row = dict[str, Any]\ndef read() -> Row: ...\n",
        "from typing import Any\nRow = dict[str, Any]\ndef read(Row: type) -> Row: ...\n",
    ],
)
def test_skips_unproven_implicit_aliases(source: str) -> None:
    assert _check(source) == []


def test_implicit_alias_honors_suppression() -> None:
    source = (
        "from typing import Any\n"
        "Row = dict[str, Any]  # sarj-noqa: SARJ447 — compatibility with external rows\n"
        "def read() -> Row: ...\n"
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any, cast\nvalue = cast(dict[str, Any], raw)\n",
        "from typing import Any\nfrom pydantic import TypeAdapter\nadapter = TypeAdapter(dict[str, Any])\n",
        "from typing import Any\nvalue = None  # type: dict[str, Any]\n",
    ],
)
def test_flags_runtime_and_legacy_type_expressions(source: str) -> None:
    assert len(_check(source)) == 1


def test_import_provenance_and_shadowing_avoid_false_positives() -> None:
    source = """
from vendor import Any, Mapping
class dict: ...
a: Mapping[str, Any]
b: dict[str, Any]
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any\ndef use():\n    dict = CustomMap\n    value: dict[str, Any]\n",
        ("from typing import Any, cast\ndef use():\n    cast = custom_cast\n    return cast(dict[str, Any], value)\n"),
    ],
)
def test_local_shadowing_makes_type_provenance_ambiguous(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param("dict[str, Annotated[int, Any]]", id="any-is-metadata"),
        pytest.param("Annotated[int, dict[str, Any]]", id="mapping-is-metadata"),
        pytest.param('dict[str, Literal["Any"]]', id="literal-string"),
        pytest.param("dict[str, Custom[int, Any]]", id="unknown-parameter-positions"),
    ],
)
def test_metadata_and_literal_values_do_not_erase_types(annotation: str) -> None:
    assert _check(f"from typing import Annotated, Any, Literal\nvalue: {annotation}\n") == []


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param("dict[str, Annotated[Any, 'tag']]", id="annotated-any-type"),
        pytest.param("Annotated[dict[str, Any], 'tag']", id="annotated-mapping-type"),
        pytest.param("dict[str, list[Any]]", id="builtin-type-argument"),
    ],
)
def test_actual_type_positions_remain_checked(annotation: str) -> None:
    assert len(_check(f"from typing import Annotated, Any\nvalue: {annotation}\n")) == 1


def test_metadata_use_does_not_make_a_runtime_value_a_type_alias() -> None:
    assert (
        _check("from typing import Annotated, Any\nMetadata = dict[str, Any]\nvalue: Annotated[int, Metadata]\n") == []
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from typing import Any, override\nclass Child(Parent):\n    @override\n    def value(self, data: dict[str, Any]) -> dict[str, Any]: return data\n",
            id="explicit-override-signature",
        ),
        pytest.param(
            "from typing import Any\nclass Child(Parent):\n    from typing import override\n    @override\n    def value(self) -> dict[str, Any]: return {}\n",
            id="class-local-override",
        ),
        pytest.param(
            "from typing import Any\nclass Child(Parent):\n    from typing import override as inherited\n    @inherited\n    def value(self) -> dict[str, Any]: return {}\n",
            id="class-local-override-alias",
        ),
        pytest.param(
            "from typing import Any\nclass Child(Parent):\n    import typing as t\n    @t.override\n    def value(self) -> dict[str, Any]: return {}\n",
            id="class-local-override-namespace",
        ),
        pytest.param(
            "import typing as t\nclass Child(Parent):\n    @t.override\n    def value(self) -> dict[str, t.Any]: return {}\n",
            id="namespace-override",
        ),
        pytest.param(
            "from typing_extensions import Any, override as inherited\nclass Child(Parent):\n    @inherited\n    async def value(self) -> dict[str, Any]: return {}\n",
            id="extension-override-alias",
        ),
        pytest.param(
            "from typing import Any\nfrom pydantic import BaseModel as Model\nclass Child(Model):\n    def model_dump(self, **kwargs) -> dict[str, Any]: return super().model_dump(**kwargs)\n",
            id="pydantic-public-dump-return",
        ),
    ],
)
def test_inherited_public_signature_contracts_are_preserved(source: str) -> None:
    assert not _check(source)


def test_override_exemption_does_not_hide_local_type_erasure() -> None:
    source = (
        "from typing import Any, cast, override\nfrom pydantic import TypeAdapter\n"
        "class Child(Parent):\n    @override\n    def value(self) -> dict[str, Any]:\n"
        "        local: dict[str, Any] = {}\n        cast(dict[str, Any], local)\n"
        "        TypeAdapter(dict[str, Any])\n        return local\n"
    )
    assert len(_check(source)) == 3


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from typing import Any, override\n@override\ndef value() -> dict[str, Any]: return {}\n",
            id="standalone-function",
        ),
        pytest.param(
            "from typing import Any, override\nclass Child(Parent):\n    override = custom\n    @override\n    def value(self) -> dict[str, Any]: return {}\n",
            id="shadowed-override",
        ),
        pytest.param(
            "from typing import Any\nfrom custom import BaseModel\nclass Child(BaseModel):\n    def model_dump(self) -> dict[str, Any]: return {}\n",
            id="unknown-model-base",
        ),
        pytest.param(
            "from typing import Any\nfrom pydantic import BaseModel\ndef factory(BaseModel):\n    class Child(BaseModel):\n        def model_dump(self) -> dict[str, Any]: return {}\n",
            id="lexically-shadowed-model-base",
        ),
    ],
)
def test_unproven_contract_exemptions_remain_checked(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("typing.Any = int", id="attribute-replacement"),
        pytest.param("setattr(typing, 'Any', int)", id="setattr"),
        pytest.param("from builtins import setattr as change\nchange(typing, 'Any', int)", id="setattr-alias"),
        pytest.param("typing.__dict__['Any'] = int", id="namespace-dictionary-write"),
        pytest.param("typing.__setattr__('Any', int)", id="bound-attribute-setter"),
        pytest.param("typing.__dict__.update({'Any': int})", id="namespace-dictionary-update"),
        pytest.param("namespace = typing.__dict__\nnamespace['Any'] = int", id="namespace-dictionary-escape"),
        pytest.param("from .helpers import typing", id="relative-module"),
        pytest.param("if flag:\n    import custom as typing", id="conditional-module"),
        pytest.param("alias = typing\nalias.Any = int", id="escaped-module-alias"),
        pytest.param("alias = typing.Dict\nalias.__origin__ = Custom", id="type-factory-origin-mutation"),
        pytest.param("alias = typing.Dict\nconfigure(alias)", id="type-factory-escape"),
        pytest.param(
            "class Holder:\n    import typing as local_t\n    local_t.Any = int",
            id="nested-canonical-namespace-mutation",
        ),
    ],
)
def test_mutated_or_ambiguous_type_namespaces_are_excluded(replacement: str) -> None:
    assert not _check("import typing\n" + replacement + "\ndef value() -> dict[str, typing.Any]: ...\n")


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("from .helpers import Any", id="relative-any"),
        pytest.param("if flag:\n    from custom import Any", id="conditional-any"),
        pytest.param("from .helpers import dict", id="relative-container"),
        pytest.param("if flag:\n    from custom import str", id="conditional-key-type"),
        pytest.param("globals()['Any'] = int", id="global-type-binding-write"),
        pytest.param("namespace = globals()\nnamespace['Any'] = int", id="global-type-namespace-escape"),
        pytest.param("namespace = globals\nnamespace()['Any'] = int", id="aliased-global-function"),
        pytest.param("from custom import *", id="wildcard-type-replacement"),
        pytest.param("import sys\nsys.modules['typing'].Any = int", id="module-cache-replacement"),
        pytest.param("__import__('typing').Any = int", id="dynamic-import-replacement"),
        pytest.param("from importlib import import_module as load\nload('typing').Any = int", id="aliased-loader"),
        pytest.param("__builtins__['dict'] = Custom", id="implicit-builtin-replacement"),
    ],
)
def test_replaced_named_type_bindings_are_excluded(replacement: str) -> None:
    assert not _check("from typing import Any\n" + replacement + "\ndef value() -> dict[str, Any]: ...\n")


def test_named_type_factory_escape_invalidates_its_canonical_origin() -> None:
    source = "from typing import Dict, Any\nalias = Dict\nsetattr(alias, '__origin__', Custom)\ndef value() -> Dict[str, Any]: ...\n"
    assert not _check(source)


@pytest.mark.parametrize(
    "escape",
    ["configure(Dict)", "providers = [Dict]", "providers = (Dict,)", "configure(t.Dict)", "providers = [t.Dict]"],
)
def test_mapping_provider_runtime_escapes_are_unproven(escape: str) -> None:
    source = "import typing as t\nfrom typing import Dict, Any\n" + escape + "\ndef value() -> Dict[str, Any]: ...\n"
    assert not _check(source)


@pytest.mark.parametrize("value", ["Any", "t.Any"])
def test_harmless_any_value_assignment_preserves_other_mapping_checks(value: str) -> None:
    source = "import typing as t\nfrom typing import Any\nPlain = " + value + "\ndef value() -> dict[str, Any]: ...\n"
    assert len(_check(source)) == 1


def test_mapping_provider_type_positions_preserve_an_unrelated_erasure_finding() -> None:
    source = "from typing import Any, Dict, TypeAlias, cast\nfrom pydantic import TypeAdapter\nRecord: TypeAlias = Dict[str, int]\ndef consume(value: tuple[Dict, ...]) -> None: ...\ncast(Dict, value)\nTypeAdapter(Dict)\ndef details() -> Dict[str, Any]: ...\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "escape",
    [
        "configure(Dict[str, Any])",
        "providers = [Dict[str, Any]]",
        "configure(t.Dict[str, Any])",
        "providers = (t.Dict[str, Any],)",
    ],
)
def test_parameterized_mapping_provider_runtime_escapes_are_unproven(escape: str) -> None:
    source = "import typing as t\nfrom typing import Dict, Any\n" + escape + "\ndef value() -> Dict[str, Any]: ...\n"
    assert not _check(source)


@pytest.mark.parametrize("alias", ["Record = Dict[str, Any]", "Record: TypeAlias = Dict[str, Any]"])
def test_parameterized_mapping_aliases_in_type_positions_remain_checked(alias: str) -> None:
    source = "from typing import Any, Dict, TypeAlias\n" + alias + "\ndef value() -> Record: ...\n"
    assert len(_check(source)) == 1


def test_parameterized_mapping_casts_and_adapters_remain_checked() -> None:
    source = "from typing import Any, Dict, cast\nfrom pydantic import TypeAdapter\ncast(Dict[str, Any], value)\nTypeAdapter(Dict[str, Any])\n"
    assert len(_check(source)) == 2


@pytest.mark.parametrize(
    "alias",
    [
        "Provider: TypeAlias = Dict",
        "Provider: TypeAlias = Dict[str, Any]",
        "Provider: TypeAlias = Dict\nOther: TypeAlias = Provider",
    ],
)
def test_explicit_mapping_provider_alias_runtime_mutation_is_unproven(alias: str) -> None:
    name = "Other" if "Other" in alias else "Provider"
    source = (
        "from typing import Any, Dict, TypeAlias\n"
        + alias
        + "\nsetattr("
        + name
        + ", '__origin__', Custom)\ndef value() -> Dict[str, Any]: ...\n"
    )
    assert not _check(source)


def test_clean_explicit_provider_alias_chain_preserves_unrelated_erasure() -> None:
    source = "from typing import Any, Dict, TypeAlias\nProvider: TypeAlias = Dict\nOther: TypeAlias = Provider\ndef consume(value: Other) -> None: ...\ndef value() -> Dict[str, Any]: ...\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any\nclass Rows[Any]:\n    rows: dict[str, Any]\n",
        "from typing import Any\ndef read[Any](rows: dict[str, Any]): ...\n",
        "from typing import Any\ndef read[Any]() -> dict[str, Any]: ...\n",
        "from typing import Any\ntype Rows[Any] = dict[str, Any]\n",
        "from typing import Any\ndef outer[Any]():\n    def read(rows: dict[str, Any]): ...\n",
        "from typing import Any\nclass Rows[Any]:\n    def read(self) -> dict[str, Any]: ...\n",
    ],
)
def test_generic_type_parameter_is_not_the_outer_any_provider(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any\nclass Rows[T]:\n    rows: dict[str, Any]\n",
        "from typing import Any\ndef read[T](rows: dict[str, Any]): ...\n",
        "from typing import Any\ndef read[T]() -> dict[str, Any]: ...\n",
        "from typing import Any\nclass Rows[Any]: pass\nrows: dict[str, Any]\n",
    ],
)
def test_unrelated_or_sibling_generic_parameters_preserve_actual_any_findings(source: str) -> None:
    [finding] = _check(source)
    assert finding.code == "SARJ447"


@pytest.mark.parametrize(
    "source",
    [
        "from typing import Any\ndef read[T](value: tuple[T, dict[str, Any]]): ...\n",
        "from typing import Any\ndef read[T](value: dict[str, tuple[T, Any]]): ...\n",
    ],
)
def test_unrelated_generic_member_does_not_hide_independent_any_erasure(source: str) -> None:
    [finding] = _check(source)
    assert finding.code == "SARJ447"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from typing import Any, cast\ndef read[Any](value=cast(dict[str, Any], {})): ...\n", 1),
        ("from typing import Any, cast\n@decorate(cast(dict[str, Any], {}))\ndef read[Any](): ...\n", 1),
        ("from typing import Any\ndef read[Any]() -> dict[str, Any]: ...\n", 0),
        ("from typing import Any, cast\ndef read[Any]():\n    value = cast(dict[str, Any], {})\n", 0),
        ("from typing import Any, cast\ndef outer[Any]():\n    def read(value=cast(dict[str, Any], {})): ...\n", 0),
        ("from typing import Any\nclass Rows[Any](Base[dict[str, Any]]): ...\n", 0),
        ("from typing import Any, cast\n@decorate(cast(dict[str, Any], {}))\nclass Rows[Any]: ...\n", 1),
        ("from typing import Any\ndef read[Any](value: dict[str, Any]): ...\n", 0),
        ("from typing import Any\nT = Any\ndef read[T](value: tuple[T, dict[str, Any]]): ...\n", 1),
        ("from typing import Any\ntype T = Any\ndef read[T](value: tuple[T, dict[str, Any]]): ...\n", 1),
        ("from typing import Any, Annotated\nT = Any\ndef read[T](value: Annotated[dict[str, Any], T]): ...\n", 1),
        ("import typing\nfrom typing import Any\ntype Rows[Any] = tuple[Any, dict[str, typing.Any]]\n", 1),
        (
            "from typing import Any\ntype T = Any\ntype Actual = T\ndef read[T](value: tuple[T, dict[str, Actual]]): ...\n",
            1,
        ),
        ("from typing import Any as Dynamic\ndef read[Dynamic](value: dict[str, Dynamic]): ...\n", 0),
        ("import typing\ndef read[typing](value: dict[str, typing.Any]): ...\n", 0),
        ("from typing import Any, cast\nclass Rows[Any](cast(dict[str, Any], {})): ...\n", 0),
        (
            "from typing import Any, cast\ndef outer[Any]():\n    read = lambda value=cast(dict[str, Any], {}): value\n",
            0,
        ),
    ],
)
def test_native_generic_annotation_scope_preserves_provider_identity(source: str, expected: int) -> None:
    assert len(_check(source)) == expected
