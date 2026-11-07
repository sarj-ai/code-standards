from __future__ import annotations

from dataclasses import dataclass

from sarj_rule_contracts import RuleEngine, RuleSpec


@dataclass(frozen=True, slots=True, kw_only=True)
class TypeScriptRuleSpec(RuleSpec):
    requires_type_information: bool | None = None
    runtime_imports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        RuleSpec.__post_init__(self)
        if self.engine is not RuleEngine.OXLINT:
            msg = "TypeScript execution capabilities require the Oxlint engine"
            raise ValueError(msg)
        if self.requires_type_information is not None and type(self.requires_type_information) is not bool:
            msg = "rule type-information requirement must be a bool or None"
            raise TypeError(msg)
        if len(self.runtime_imports) != len(set(self.runtime_imports)) or any(
            not name.strip() for name in self.runtime_imports
        ):
            msg = "rule runtime imports must be unique and non-empty"
            raise ValueError(msg)
