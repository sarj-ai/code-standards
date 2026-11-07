from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

import pytest
from sarj_rule_contracts import Language, RuleCategory, RuleEngine, RuleId

from sarj_standards.libs.rules import DocumentedRule, RuleCatalogDocument
from sarj_standards.libs.rules.capabilities import TypeScriptRuleSpec


def _spec() -> TypeScriptRuleSpec:
    return TypeScriptRuleSpec(
        engine=RuleEngine.OXLINT,
        rule_id=RuleId("capability-probe"),
        code=None,
        summary="Describe native rule prerequisites.",
        rationale="Keep evaluated coverage visible.",
        remediation="Supply declared prerequisites.",
        category=RuleCategory("maintainability"),
        languages=frozenset({Language.TYPESCRIPT}),
    )


def test_legacy_rule_capabilities_remain_unspecified() -> None:
    spec = _spec()
    assert spec.requires_type_information is None
    assert spec.runtime_imports == ()


@pytest.mark.parametrize("required", [True, False, None])
def test_explicit_type_information_requirements(required: bool | None) -> None:
    spec = replace(_spec(), requires_type_information=required, runtime_imports=("zod",))
    assert spec.requires_type_information is required
    assert spec.runtime_imports == ("zod",)
    document = RuleCatalogDocument((DocumentedRule(spec, PurePosixPath("rule.ts"), PurePosixPath("rule.test.ts")),))
    rules = document.as_public_dict()["rules"]
    assert isinstance(rules, list)
    public = rules[0]
    assert isinstance(public, dict)
    assert public["requiresTypeInformation"] is required
    assert public["runtimeImports"] == ["zod"]


def test_capabilities_reject_integer_boolean_coercion() -> None:
    with pytest.raises(TypeError, match="bool or None"):
        replace(_spec(), requires_type_information=1)


@pytest.mark.parametrize("imports", [("zod", "zod"), ("",), (" ",)])
def test_runtime_imports_are_unique_and_nonempty(imports: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="unique and non-empty"):
        replace(_spec(), runtime_imports=imports)


def test_capability_adapters_require_their_native_engine() -> None:
    with pytest.raises(ValueError, match="Oxlint engine"):
        replace(_spec(), engine=RuleEngine.PYTHON)
