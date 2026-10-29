from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_before_validator_input_mutation import NoBeforeValidatorInputMutation


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import model_validator\nclass Ordinary:\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @staticmethod\n    @model_validator(mode='before')\n    def normalize(data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @unknown_wrapper\n    def normalize(data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n    def normalize(self): return self\n",
        "from pydantic import BaseModel, model_validator\nfrom plugin import UnknownMixin\nclass Record(UnknownMixin, BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n    locals()['normalize'] = lambda self: self\n",
        "from pydantic import BaseModel, model_validator\nfrom custom_hooks import configure\nconfigure(model_validator)\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\ndef create():\n    class Record:\n        @model_validator(mode='before')\n        @classmethod\n        def normalize(cls, data: dict[str, object]):\n            data['name'] = 'new'\n            return data\ncreate()\n",
        "import typing\nfrom pydantic import BaseModel, model_validator\nclass Replacement(BaseModel):\n    name: str\ntyping.final = lambda original: Replacement\n@typing.final\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
    ],
)
def test_requires_effective_validator_on_a_proven_pydantic_model(source: str) -> None:
    assert NoBeforeValidatorInputMutation().check(Path("app/records.py"), source) == []


def test_plain_before_validator_receives_raw_data_in_its_first_parameter() -> None:
    source = "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    def normalize(data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n"
    assert len(NoBeforeValidatorInputMutation().check(Path("app/records.py"), source)) == 1


@pytest.mark.parametrize("descriptor", ["classmethod", "staticmethod"])
@pytest.mark.parametrize(
    "provider_change",
    [
        "import builtins\nbuiltins.{descriptor} = replacement\n",
        "__builtins__['{descriptor}'] = replacement\n",
        "from builtins import {descriptor} as original\nconfigure(original)\n",
    ],
)
def test_explicit_validator_descriptor_requires_an_untouched_builtin_provider(
    descriptor: str, provider_change: str
) -> None:
    receiver = "cls, " if descriptor == "classmethod" else ""
    source = (
        provider_change.format(descriptor=descriptor)
        + "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
        + f"    @model_validator(mode='before')\n    @{descriptor}\n"
        + f"    def normalize({receiver}data: dict[str, object]):\n"
        + "        data['name'] = 'new'\n        return data\n"
    )
    assert NoBeforeValidatorInputMutation().check(Path("app/records.py"), source) == []


@pytest.mark.parametrize("descriptor", ["classmethod", "staticmethod"])
def test_canonical_validator_descriptor_remains_blocking(descriptor: str) -> None:
    receiver = "cls, " if descriptor == "classmethod" else ""
    source = (
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
        f"    @model_validator(mode='before')\n    @{descriptor}\n"
        f"    def normalize({receiver}data: dict[str, object]):\n"
        "        data['name'] = 'new'\n        return data\n"
    )
    [finding] = NoBeforeValidatorInputMutation().check(Path("app/records.py"), source)
    assert finding.severity.value == "error"


@pytest.mark.parametrize(
    "provider_change",
    ["import builtins\nbuiltins.classmethod = replacement\n", "__builtins__['classmethod'] = replacement\n"],
)
def test_automatic_classmethod_conversion_requires_an_untouched_provider(provider_change: str) -> None:
    source = (
        provider_change
        + "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
        + "    @model_validator(mode='before')\n    def normalize(cls, data: dict[str, object]):\n"
        + "        data['name'] = 'new'\n        return data\n"
    )
    assert NoBeforeValidatorInputMutation().check(Path("app/records.py"), source) == []


def test_canonical_automatic_classmethod_conversion_remains_blocking() -> None:
    source = (
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
        "    @model_validator(mode='before')\n    def normalize(cls, data: dict[str, object]):\n"
        "        data['name'] = 'new'\n        return data\n"
    )
    [finding] = NoBeforeValidatorInputMutation().check(Path("app/records.py"), source)
    assert finding.severity.value == "error"


@pytest.mark.parametrize(
    "customization", ["configure(Record)", "Record.__pydantic_validator__ = replacement", "alias = Record"]
)
def test_model_class_must_retain_its_validation_contract(customization: str) -> None:
    source = (
        "from pydantic import BaseModel, model_validator\nfrom custom_hooks import configure\nclass Record(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n"
        + customization
        + "\n"
    )
    assert NoBeforeValidatorInputMutation().check(Path("app/records.py"), source) == []


@pytest.mark.parametrize(
    "alias_import",
    [
        "from app.records import Record as OwnedRecord\ndetach(OwnedRecord)\n",
        "import app.records as owned\ndetach(owned.Record)\n",
        "from app.records import Record as OwnedRecord\nOwnedRecord = OwnedRecord\ndetach(OwnedRecord)\n",
        "import app.records as owned\nowned = owned\ndetach(owned.Record)\n",
        "def alter():\n    from app.records import Record as Alias\n    detach(Alias)\nalter()\n",
        "def alter():\n    import app.records as owned\n    detach(owned.Record)\nalter()\n",
        "def detach_module(module): detach(module.Record)\nimport app.records as owned\ndetach_module(owned)\n",
        "def detach_module(module): detach(module.Record)\nimport app.records\ndetach_module(app.records)\n",
        "def detach_module(module): detach(module.Record)\nfrom app import records as owned\ndetach_module(owned)\n",
        "def types(): yield Record\ndetach(next(types()))\n",
        "if (owned := Record): detach(owned)\n",
        "for owned in (Record,): detach(owned)\n",
        "match Record:\n    case owned: detach(owned)\n",
        "def detach_default(owner=Record): detach(owner)\ndetach_default()\n",
        "class Registry:\n    def __getitem__(self, owner): detach(owner)\nRegistry()[Record]\n",
        "class Registry:\n    def __eq__(self, owner): detach(owner); return True\nif Registry() == Record: pass\n",
    ],
)
@pytest.mark.parametrize("absolute_path", [False, True])
def test_self_module_with_imported_model_alias_abstains(tmp_path: Path, alias_import: str, absolute_path: bool) -> None:
    source = (
        "from pydantic import BaseModel, model_validator\n"
        "class Replacement(BaseModel):\n    name: str\n"
        "def detach(owner):\n    owner.__pydantic_validator__ = Replacement.__pydantic_validator__\n"
        "class Record(BaseModel):\n    name: str\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: dict[str, object]):\n"
        "        data['name'] = 'new'\n        return data\n" + alias_import
    )
    path = tmp_path / "app" / "records.py" if absolute_path else Path("app/records.py")
    assert NoBeforeValidatorInputMutation().check(path, source) == []


@pytest.mark.parametrize(
    "constructor_call",
    [
        "from app.records import Record as Alias\nAlias(name='old')\n",
        "import app.records as owned\nowned.Record(name='old')\n",
    ],
)
def test_known_self_module_direct_imported_constructor_keeps_error(constructor_call: str) -> None:
    source = (
        "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: dict[str, object]):\n"
        "        data['name'] = 'new'\n        return data\n" + constructor_call
    )
    [finding] = NoBeforeValidatorInputMutation().check(Path("app/records.py"), source)
    assert finding.severity.value == "error"


def test_validator_parent_module_must_not_escape_to_unknown_configuration() -> None:
    source = "from pydantic import BaseModel\nimport pydantic.functional_validators\nfrom custom_hooks import configure\nconfigure(pydantic.functional_validators)\nclass Record(BaseModel):\n    name: str\n    @pydantic.functional_validators.model_validator(mode='before')\n    @classmethod\n    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n"
    assert NoBeforeValidatorInputMutation().check(Path("app/records.py"), source) == []


@pytest.mark.parametrize("member_value", ["Descriptor()", "guard"])
def test_class_creation_descriptor_cannot_detach_the_before_validator(member_value: str) -> None:
    source = (
        "from typing import ClassVar\nfrom pydantic import BaseModel, model_validator\n"
        "class Descriptor:\n"
        "    def __set_name__(self, owner, name):\n"
        "        def identity(cls, value): return value\n"
        "        owner.normalize = classmethod(identity)\n"
        "guard = Descriptor()\nclass Record(BaseModel):\n    name: str\n"
        f"    marker: ClassVar[Descriptor] = {member_value}\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: dict[str, object]):\n"
        "        data['name'] = 'new'\n        return data\n"
    )
    assert NoBeforeValidatorInputMutation().check(Path("app/records.py"), source) == []


def test_literal_fields_and_canonical_pydantic_class_values_remain_blocking() -> None:
    source = (
        "from pydantic import BaseModel, Field, ConfigDict, model_validator\n"
        "class Record(BaseModel):\n    name: str = Field(default='old', min_length=1)\n"
        "    tags: list[str] = Field(default_factory=list)\n"
        "    model_config = ConfigDict(frozen=True)\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: dict[str, object]):\n"
        "        data['name'] = 'new'\n        return data\n"
    )
    [finding] = NoBeforeValidatorInputMutation().check(Path("app/records.py"), source)
    assert finding.severity.value == "error"


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic

_HEADER = "from pydantic import BaseModel, model_validator\nclass Record(BaseModel):\n    name: str\n"
_DECORATOR = "    @model_validator(mode='before')\n    @classmethod\n"
_BAD = {
    "raw-item-write": "    def normalize(cls, data: dict[str, object]):\n        data['name'] = 'new'\n        return data\n",
    "stable-alias": "    def normalize(cls, data: dict[str, object]):\n        alias = data\n        alias['name'] = 'new'\n        return data\n",
    "typed-pop": "    def normalize(cls, data: dict[str, object]):\n        data.pop('legacy', None)\n        return data\n",
    "narrowed-input": "    def normalize(cls, data: object):\n        if isinstance(data, dict):\n            data.pop('legacy', None)\n        return data\n",
    "unknown-raw-type-write": "    def normalize(cls, data: object):\n        data['name'] = 'new'\n        return data\n",
    "shallow-dict-child": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = dict(data)\n        copied['nested']['name'] = 'new'\n        return copied\n",
}
_GOOD = {
    "copy-before-write": "    def normalize(cls, data: dict[str, object]):\n        data = dict(data)\n        data['name'] = 'new'\n        return data\n",
    "dict-expansion": "    def normalize(cls, data: dict[str, object]):\n        return {**data, 'name': 'new'}\n",
    "copy-before-pop": "    def normalize(cls, data: dict[str, object]):\n        copied = data.copy()\n        copied.pop('legacy', None)\n        return copied\n",
    "unknown-method": "    def normalize(cls, data: object):\n        data.pop('legacy')\n        return data\n",
    "nested-function-shadowing": "    def normalize(cls, data):\n        def helper(data):\n            data['name'] = 'new'\n        return data\n",
}
_GOOD.update(
    {
        "spread-with-fresh-child": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = {**data, 'nested': {}}\n        copied['nested']['name'] = 'new'\n        return copied\n",
        "fresh-child-assignment": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = dict(data)\n        copied['nested'] = {}\n        copied['nested']['name'] = 'new'\n        return copied\n",
    }
)
_BAD.update(
    {
        "spread-shares-nested-values": "    def normalize(cls, data: dict[str, dict[str, str]]):\n        copied = {**data}\n        copied['nested']['name'] = 'new'\n        return copied\n",
        "guard-before-mutator": "    def normalize(cls, data: object):\n        if not isinstance(data, dict):\n            return data\n        data.pop('legacy', None)\n        return data\n",
        "cast-retains-input-identity": "    def normalize(cls, data: object):\n        from typing import cast\n        payload = cast(dict[str, object], data)\n        payload.pop('legacy', None)\n        return payload\n",
    }
)
_CASES = (
    EvaluationCase(
        "fresh-dict-keyword-override",
        Language.PYTHON,
        _HEADER
        + _DECORATOR
        + "    def normalize(cls, data: dict[str, object]):\n        copied = dict(data, nested={})\n        copied['nested']['name'] = 'new'\n        return copied\n",
    ),
    *(
        EvaluationCase(key, Language.PYTHON, _HEADER + _DECORATOR + source, ExpectedOutcome.MATCH)
        for key, source in _BAD.items()
    ),
    *(EvaluationCase(key, Language.PYTHON, _HEADER + _DECORATOR + source) for key, source in _GOOD.items()),
    EvaluationCase(
        "after-validator",
        Language.PYTHON,
        _HEADER
        + "    @model_validator(mode='after')\n    def normalize(self):\n        self.name = 'new'\n        return self\n",
    ),
    EvaluationCase(
        "shadowed-decorator",
        Language.PYTHON,
        "def model_validator(**kwargs): return unknown\n"
        + _HEADER.replace(", model_validator", "")
        + _DECORATOR
        + "    def normalize(cls, data):\n        data['name'] = 'new'\n",
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "def normalize(:\n"),
)


def _check(source: str, path: Path = Path("app/models.py")) -> list[Diagnostic]:
    return NoBeforeValidatorInputMutation().check(path, source)


@pytest.mark.parametrize("receiver", ["parent['nested']", "child"])
@pytest.mark.parametrize("borrowed", [False, True])
def test_owned_mapping_child_replacement_updates_contained_aliases(receiver: str, *, borrowed: bool) -> None:
    child = "{'values': []}" if borrowed else "dict(data)"
    replacement = "data['values']" if borrowed else "[]"
    source = (
        "from pydantic import BaseModel, model_validator\n\n\n"
        "class Record(BaseModel):\n    values: list[str]\n\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: dict[str, list[str]]) -> dict[str, list[str]]:\n"
        f"        child = {child}\n        parent = {{'nested': child}}\n"
        f"        child['values'] = {replacement}\n"
        f"        {receiver}['values'].append('changed')\n        return parent['nested']\n"
    )

    findings = _check(source)

    assert [(finding.code, finding.line, finding.col, finding.severity.value) for finding in findings] == (
        [("SARJ482", 13, 9, "error")] if borrowed else []
    )


def test_equivalent_borrowed_mapping_summaries_survive_join() -> None:
    source = (
        "from pydantic import BaseModel, model_validator\n"
        "class Record(BaseModel):\n    values: list[str]\n"
        "    @model_validator(mode='before')\n    @classmethod\n"
        "    def normalize(cls, data: dict[str, dict[str, list[str]]]):\n"
        "        left = data['left']\n        right = data['right']\n"
        "        if data:\n            parents = [left, right]\n"
        "        else:\n            parents = [left, right]\n"
        "        parents[0]['values'].append('unsafe')\n"
        "        return {'values': parents[0]['values']}\n"
    )

    findings = _check(source)

    assert [(finding.code, finding.line, finding.col, finding.severity.value) for finding in findings] == [
        ("SARJ482", 13, 9, "error")
    ]


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_validator_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert all(finding.code == "SARJ482" for finding in findings)


def test_documented_examples() -> None:
    verify_native_rule(NoBeforeValidatorInputMutation, analyze)


def test_field_validator_alias() -> None:
    source = (
        "from pydantic import BaseModel, field_validator as validate\n"
        "class Record(BaseModel):\n    tags: list[str]\n"
        "    @validate('tags', mode='before')\n    @classmethod\n"
        "    def normalize(cls, values: list[str]):\n        values.sort()\n        return values\n"
    )
    [finding] = _check(source)
    assert (finding.line, finding.col) == (7, 9)


def test_exact_suppression_and_generated_sources() -> None:
    source = (_HEADER + _DECORATOR + _BAD["raw-item-write"]).replace(
        "data['name'] = 'new'", "data['name'] = 'new'  # sarj-noqa: SARJ482 — explicitly shared normalization"
    )
    assert _check(source) == []
    assert _check(_HEADER + _DECORATOR + _BAD["raw-item-write"], Path("generated/models.py")) == []
