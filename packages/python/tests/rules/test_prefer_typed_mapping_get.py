from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Rule, Severity
from sarj_python_lint.rules.prefer_typed_mapping_get import PreferTypedMappingGet
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import RequirePydanticForMappingShape


def test_documented_examples() -> None:
    verify_native_rule(PreferTypedMappingGet, analyze)


CASES = (
    ("opaque", "def f(raw: dict[str, object]): return raw.get('name')", 1),
    ("any-values", "from typing import Any\ndef f(raw: dict[str, Any]): return raw.get('name')", 1),
    ("json-values", "from pydantic import JsonValue\ndef f(raw: dict[str, JsonValue]): return raw.get('name')", 1),
    ("mapping", "from collections.abc import Mapping\ndef f(raw: Mapping[str, object]): return raw.get('name')", 1),
    ("bare-dict", "def f(raw: dict): return raw.get('name')", 1),
    ("bare-mapping", "from typing import Mapping\ndef f(raw: Mapping): return raw.get('name')", 1),
    ("any-receiver", "from typing import Any as Unknown\ndef f(raw: Unknown): return raw.get('name')", 1),
    ("object-receiver", "def f(raw: object): return raw.get('name')", 1),
    ("quoted", "def f(raw: 'dict[str, object]'): return raw.get('name')", 1),
    ("type-alias", "type Raw = dict[str, object]\ndef f(raw: Raw): return raw.get('name')", 1),
    ("local-alias", "def f(raw: dict[str, object]):\n    alias = raw\n    return alias.get('name')", 1),
    ("dynamic-key", "def f(raw: dict[str, object], key: str): return raw.get(key)", 1),
    ("default", "def f(raw: dict[str, object]): return raw.get('name', '')", 1),
    ("json-loads", "import json\ndef f(text: str):\n    raw = json.loads(text)\n    return raw.get('name')", 1),
    ("json-direct", "from json import loads as parse\ndef f(text: str): return parse(text).get('name')", 1),
    ("json-load", "import json\ndef f(stream):\n    raw = json.load(stream)\n    return raw.get('name')", 1),
    ("nested-get", "def f(raw: dict[str, object]): return raw.get('state').get('name')", 1),
    ("nested-index", "def f(raw: dict[str, object]): return raw['state'].get('name')", 1),
    ("typed-map", "def f(raw: dict[str, str]): return raw.get('name')", 0),
    ("typed-union", "def f(raw: dict[str, str | int]): return raw.get('name')", 0),
    (
        "typed-dict",
        "from typing import TypedDict\nclass State(TypedDict):\n    name: str\ndef f(raw: State): return raw.get('name')",
        0,
    ),
    ("unknown-parameter", "def f(raw): return raw.get('name')", 0),
    (
        "application-get",
        "class Cache:\n    def get(self, key): return key\ndef f(raw: Cache): return raw.get('name')",
        0,
    ),
    ("reassigned", "def f(raw: dict[str, object]):\n    raw = other\n    return raw.get('name')", 0),
    ("shadowed-dict", "class dict: pass\ndef f(raw: dict[str, object]): return raw.get('name')", 0),
    ("shadowed-any", "from typing import Any\ndef f[Any](raw: Any): return raw.get('name')", 0),
    ("json-hook", "import json\ndef f(text): return json.loads(text, object_hook=Record).get('name')", 0),
    ("shadowed-json", "import json\ndef f(json, text): return json.loads(text).get('name')", 0),
    ("custom-loads", "from app import loads\ndef f(text): return loads(text).get('name')", 0),
    (
        "precise-local",
        "import json\nfrom app import State\ndef f(text):\n    raw: State = json.loads(text)\n    return raw.get('name')",
        0,
    ),
    (
        "validation-callback",
        "from pydantic import BaseModel, model_validator\nclass State(BaseModel):\n    name: str\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, raw: dict[str, object]):\n        return {'name': raw.get('name', '')}",
        0,
    ),
    ("wildcard", "from app import *\ndef f(raw: dict[str, object]): return raw.get('name')", 0),
    ("malformed", "def f(:", 0),
    (
        "local-class-shadows-alias",
        "type Raw = dict\ndef outer():\n    class Raw: pass\n    def f(raw: Raw): return raw.get('name')",
        0,
    ),
    (
        "local-value-shadows-alias",
        "type Raw = dict[str, object]\ndef outer():\n    Raw: type[str] = str\n    def f(raw: Raw): return raw.get('name')",
        0,
    ),
    ("alias-definition-scope", "type Raw = dict\ndef f[dict](raw: Raw): return raw.get('name')", 1),
    ("shadowed-type-alias", "type Raw = dict\ndef f[Raw](raw: Raw): return raw.get('name')", 0),
    (
        "local-return",
        "def parse(text: str) -> dict[str, object]: ...\ndef f(text: str): return parse(text).get('name')",
        1,
    ),
    (
        "typed-local-return",
        "def parse(text: str) -> dict[str, str]: ...\ndef f(text: str): return parse(text).get('name')",
        0,
    ),
    (
        "decorated-local-return",
        "@decorate\ndef parse(text: str) -> dict[str, object]: ...\ndef f(text: str): return parse(text).get('name')",
        0,
    ),
)


@pytest.mark.parametrize(("label", "source", "count"), CASES, ids=[case[0] for case in CASES])
def test_mapping_contracts(label: str, source: str, count: int) -> None:
    findings = PreferTypedMappingGet().check(Path("app/state.py"), source)
    assert len(findings) == count, label
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_shape_diagnostic_precedence_and_selection() -> None:
    source = "def f(raw: dict[str, object]): return isinstance(raw.get('name'), str)"
    rules: list[Rule] = [PreferTypedMappingGet(), RequirePydanticForMappingShape()]
    assert [finding.code for finding in check_source(rules, Path("app/state.py"), source)] == ["SARJ521"]
    assert [finding.code for finding in check_source(rules[:1], Path("app/state.py"), source)] == ["SARJ535"]


def test_exact_suppression_and_generated_source() -> None:
    source = CASES[0][1] + "  # sarj-noqa: SARJ535 -- open plugin metadata is intentionally opaque\n"
    assert check_source([PreferTypedMappingGet()], Path("app/state.py"), source) == []
    assert PreferTypedMappingGet().check(Path("vendor/state.py"), CASES[0][1]) == []
