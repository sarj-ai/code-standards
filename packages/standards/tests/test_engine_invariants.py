from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from sarj_standards import api
from sarj_standards.libs.diagnostics import Diagnostic, Location, Severity
from sarj_standards.libs.linting import policy
from sarj_standards.libs.release.tags import RELEASE_TARGETS
from sarj_standards.libs.repository import rule_changes, rule_lifecycle
from sarj_standards.libs.rules import RuleEngine


_ROOT = Path(__file__).parents[3]


@dataclass(frozen=True, slots=True)
class _EngineCase:
    engine: RuleEngine
    family: str
    release_target: str
    sources: frozenset[str]


_CASES = (
    _EngineCase(RuleEngine.ESLINT, "typescript", "typescript", frozenset(("eslint",))),
    _EngineCase(RuleEngine.IAC, "iac", "iac", frozenset(("iac", "sarj-iac-lint"))),
    _EngineCase(RuleEngine.PYTHON, "python", "python", frozenset(("python", "sarj-python-lint"))),
    _EngineCase(RuleEngine.SQL, "sql", "sql", frozenset(("sql", "sarj-sql-lint"))),
    _EngineCase(RuleEngine.TEXT, "text", "standards", frozenset(("text", "sarj-text-lint"))),
)


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)  # pyright: ignore[reportUnknownVariableType]
    return value  # pyright: ignore[reportUnknownVariableType]


def _array(value: object) -> list[object]:
    assert isinstance(value, list)
    return value  # pyright: ignore[reportUnknownVariableType]


def _text(value: object) -> str:
    assert isinstance(value, str)
    return value


def _load(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    return _object(value)


def _diagnostic(source: str) -> Diagnostic:
    return Diagnostic(
        code="TEST001",
        message="test",
        severity=Severity.ERROR,
        source=source,
        location=Location("example.txt"),
    )


def test_engine_matrix_exhausts_the_public_contract_and_schema() -> None:
    expected = {case.engine for case in _CASES}
    schema = _load(_ROOT / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.schema.json")
    definitions = _object(schema["$defs"])
    rule = _object(definitions["rule"])
    properties = _object(rule["properties"])
    engine = _object(properties["engine"])

    assert expected == set(RuleEngine)
    assert {_text(value) for value in _array(engine["enum"])} == {engine.value for engine in expected}


def test_engine_family_and_release_mappings_agree() -> None:
    expected_families = {case.family: case.engine for case in _CASES}
    expected_release_targets = {case.engine.value: case.release_target for case in _CASES}

    assert dict(rule_lifecycle._ENGINE_BY_FAMILY) == expected_families  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert dict(rule_changes._ENGINE_BY_FAMILY) == {  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        family: engine.value for family, engine in expected_families.items()
    }
    assert dict(rule_changes._RELEASE_TARGET_BY_ENGINE) == expected_release_targets  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert set(expected_release_targets.values()) <= set(RELEASE_TARGETS)


def test_diagnostic_sources_resolve_to_the_same_engine_everywhere() -> None:
    expected_aliases = {source: case.engine for case in _CASES for source in case.sources}

    assert {
        source: api._engine_for_diagnostic(_diagnostic(source))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        for source in expected_aliases
    } == expected_aliases
    assert {
        source: policy._SOURCE_ENGINES.get(source, source)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        for source in expected_aliases
    } == {source: engine.value for source, engine in expected_aliases.items()}


def test_live_catalog_uses_only_declared_engine_family_pairs() -> None:
    inventory = _load(_ROOT / "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
    catalog = _load(_ROOT / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")
    family_by_key = {
        f"{case.engine.value}:{_text(entry['id'])}": _text(entry["family"])
        for case in _CASES
        for value in _array(inventory["rules"])
        if (entry := _object(value))["family"] == case.family
    }
    expected_pair = {case.engine.value: case.family for case in _CASES}

    assert family_by_key
    assert all(
        family_by_key[_text(item["key"])] == expected_pair[_text(item["engine"])]
        for value in _array(catalog["rules"])
        if (item := _object(value))
    )
